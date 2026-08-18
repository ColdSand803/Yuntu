import { SUPPORTED_CITIES } from "@/constants/preferences";

interface CitySelectProps {
  value: string;
  onChange: (city: string) => void;
  error?: string;
}

export function CitySelect({ value, onChange, error }: CitySelectProps) {
  return (
    <fieldset>
      <legend className="form-label">
        目的地 <span className="text-accent-500">*</span>
      </legend>
      <div className="flex flex-wrap gap-2">
        {SUPPORTED_CITIES.map((city) => (
          <button
            key={city}
            type="button"
            onClick={() => onChange(city)}
            className={value === city ? "tag-active" : "tag-idle"}
          >
            {city}
          </button>
        ))}
      </div>
      {error && <p className="mt-1.5 text-xs text-red-500">{error}</p>}
    </fieldset>
  );
}
