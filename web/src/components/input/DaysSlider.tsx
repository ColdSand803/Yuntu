interface DaysSliderProps {
  value: number;
  onChange: (days: number) => void;
}

const MIN = 1;
const MAX = 7;

export function DaysSlider({ value, onChange }: DaysSliderProps) {
  return (
    <fieldset>
      <legend className="form-label">
        游玩天数 <span className="text-accent-500">*</span>
      </legend>
      <div className="flex items-center gap-4">
        <input
          type="range"
          min={MIN}
          max={MAX}
          step={1}
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          className="h-2 flex-1 cursor-pointer appearance-none rounded-full bg-primary-100 accent-primary-600 [&::-webkit-slider-thumb]:h-6 [&::-webkit-slider-thumb]:w-6 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-primary-600 [&::-webkit-slider-thumb]:shadow-sm"
        />
        <span className="w-16 rounded-xl bg-primary-50 py-1.5 text-center text-sm font-semibold text-primary-700">
          {value} 天
        </span>
      </div>
      <div className="mt-1 flex justify-between px-0.5 text-xs text-sand-400">
        <span>{MIN}</span>
        <span>{MAX}</span>
      </div>
    </fieldset>
  );
}
