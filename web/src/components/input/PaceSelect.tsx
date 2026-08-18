import { PACE_OPTIONS } from "@/constants/preferences";

interface PaceSelectProps {
  value: string;
  onChange: (pace: string) => void;
}

export function PaceSelect({ value, onChange }: PaceSelectProps) {
  return (
    <fieldset>
      <legend className="form-label">旅行节奏</legend>
      <div className="flex flex-wrap gap-3">
        {PACE_OPTIONS.map((opt) => (
          <label
            key={opt.value}
            className={`flex cursor-pointer items-center gap-2 rounded-xl border px-4 py-2.5 text-sm transition-all duration-150 has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-primary-300 ${
              value === opt.value
                ? "border-primary-500 bg-primary-50 text-primary-700 shadow-sm"
                : "border-primary-100 bg-white text-primary-700 hover:border-primary-300"
            }`}
          >
            <input
              type="radio"
              name="pace"
              value={opt.value}
              checked={value === opt.value}
              onChange={() => onChange(opt.value)}
              className="sr-only"
            />
            <span
              className={`flex h-4 w-4 items-center justify-center rounded-full border-2 transition-colors ${
                value === opt.value
                  ? "border-primary-500"
                  : "border-sand-300"
              }`}
            >
              {value === opt.value && (
                <span className="h-2 w-2 rounded-full bg-primary-500" />
              )}
            </span>
            {opt.label}
          </label>
        ))}
      </div>
    </fieldset>
  );
}
