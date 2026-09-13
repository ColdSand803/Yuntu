import { Check, Minus, Plus } from "lucide-react";
import type { CinematicCompanion } from "@/types/cinematic";
import { CINEMATIC_COMPANION_OPTIONS } from "@/types/cinematic";

interface CinematicCompanionsProps {
  companion: string;
  peopleCount: number;
  onSelectCompanion: (vibe: CinematicCompanion, defaultCount: number) => void;
  onChangePeopleCount: (count: number) => void;
}

export function CinematicCompanions({
  companion,
  peopleCount,
  onSelectCompanion,
  onChangePeopleCount,
}: CinematicCompanionsProps) {
  const handleDecrement = () => {
    if (peopleCount > 1) {
      onChangePeopleCount(peopleCount - 1);
    }
  };

  const handleIncrement = () => {
    if (peopleCount < 30) {
      onChangePeopleCount(peopleCount + 1);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div className="cmp-options" role="radiogroup" aria-label="出行同行方式">
        {CINEMATIC_COMPANION_OPTIONS.map((opt) => {
          const isSelected = companion === opt.label;
          return (
            <button
              key={opt.label}
              type="button"
              role="radio"
              aria-checked={isSelected}
              className={`cmp-option-btn ${isSelected ? "is-selected" : ""}`}
              onClick={() => onSelectCompanion(opt.label, opt.defaultCount)}
            >
              <span>{opt.label}</span>
              {isSelected && <Check size={16} />}
            </button>
          );
        })}
      </div>

      <div className="cmp-people" aria-label="调整同行人数">
        <span>同行人数</span>
        <button
          type="button"
          aria-label="减少人数"
          disabled={peopleCount <= 1}
          onClick={handleDecrement}
        >
          <Minus size={15} />
        </button>
        <output aria-live="polite">{peopleCount} 人</output>
        <button
          type="button"
          aria-label="增加人数"
          disabled={peopleCount >= 30}
          onClick={handleIncrement}
        >
          <Plus size={15} />
        </button>
      </div>
    </div>
  );
}
