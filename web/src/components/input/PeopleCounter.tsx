interface PeopleCounterProps {
  value: number;
  onChange: (count: number) => void;
}

const MIN = 1;
const MAX = 10;

export function PeopleCounter({ value, onChange }: PeopleCounterProps) {
  return (
    <fieldset>
      <legend className="form-label">
        出行人数 <span className="text-accent-500">*</span>
      </legend>
      <div className="inline-flex items-center rounded-xl border border-primary-100 bg-white">
        <button
          type="button"
          disabled={value <= MIN}
          onClick={() => onChange(value - 1)}
          className="flex h-11 w-11 items-center justify-center text-lg text-primary-400 transition-colors hover:bg-primary-50 disabled:cursor-not-allowed disabled:text-sand-300"
        >
          −
        </button>
        <span className="w-12 text-center text-sm font-semibold text-primary-800">
          {value} 人
        </span>
        <button
          type="button"
          disabled={value >= MAX}
          onClick={() => onChange(value + 1)}
          className="flex h-11 w-11 items-center justify-center text-lg text-primary-400 transition-colors hover:bg-primary-50 disabled:cursor-not-allowed disabled:text-sand-300"
        >
          +
        </button>
      </div>
    </fieldset>
  );
}
