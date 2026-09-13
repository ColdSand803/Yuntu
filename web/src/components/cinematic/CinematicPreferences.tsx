import { Check } from "lucide-react";
import type { CinematicInterest, CinematicRhythm } from "@/types/cinematic";
import {
  CINEMATIC_INTEREST_OPTIONS,
  CINEMATIC_RHYTHM_OPTIONS,
} from "@/types/cinematic";

interface CinematicPreferencesProps {
  selectedInterests: string[];
  selectedRhythm: CinematicRhythm;
  onToggleInterest: (interest: CinematicInterest) => void;
  onSelectRhythm: (rhythm: CinematicRhythm) => void;
}

export function CinematicPreferences({
  selectedInterests,
  selectedRhythm,
  onToggleInterest,
  onSelectRhythm,
}: CinematicPreferencesProps) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <div>
        <span
          style={{
            display: "block",
            fontSize: "12px",
            color: "var(--cmp-accent)",
            letterSpacing: "0.15em",
            marginBottom: "8px",
          }}
        >
          旅行节奏（单选）
        </span>
        <div className="cmp-options" role="radiogroup" aria-label="旅行节奏">
          {CINEMATIC_RHYTHM_OPTIONS.map((opt) => {
            const isSelected = selectedRhythm === opt.value;
            return (
              <button
                key={opt.value}
                type="button"
                role="radio"
                aria-checked={isSelected}
                className={`cmp-option-btn ${isSelected ? "is-selected" : ""}`}
                onClick={() => onSelectRhythm(opt.value)}
              >
                <span>{opt.label}</span>
                {isSelected && <Check size={16} />}
              </button>
            );
          })}
        </div>
      </div>

      <div>
        <span
          style={{
            display: "block",
            fontSize: "12px",
            color: "var(--cmp-accent)",
            letterSpacing: "0.15em",
            marginBottom: "8px",
          }}
        >
          心动体验（多选，可不选）
        </span>
        <div className="cmp-options" role="group" aria-label="心动体验偏好">
          {CINEMATIC_INTEREST_OPTIONS.map((interest) => {
            const isSelected = selectedInterests.includes(interest);
            return (
              <button
                key={interest}
                type="button"
                role="checkbox"
                aria-checked={isSelected}
                className={`cmp-option-btn ${isSelected ? "is-selected" : ""}`}
                onClick={() => onToggleInterest(interest)}
              >
                <span>{interest}</span>
                {isSelected && <Check size={16} />}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

