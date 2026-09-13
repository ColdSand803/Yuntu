import { useDestinations } from "@/hooks/useDestinations";

interface CitySelectProps {
  value: string;
  onChange: (city: string) => void;
  error?: string;
}

export function CitySelect({ value, onChange, error }: CitySelectProps) {
  const { data: destinationsData, isLoading, error: directoryError, refetch } = useDestinations();
  const cities = destinationsData?.destinations
    .filter(dest => dest.isActive !== false)
    .map(dest => dest.name) || [];

  if (directoryError) return <div role="alert">城市目录加载失败 <button type="button" onClick={() => void refetch()}>重试</button></div>;
  return (
    <fieldset>
      <legend className="form-label">
        目的地 <span className="text-accent-500">*</span>
      </legend>
      {isLoading ? (
        <p className="text-sm text-gray-500">加载中...</p>
      ) : (
        <div className="flex flex-wrap gap-2">
          {!cities.length && <p>暂无可选城市</p>}
          {cities.map((city) => (
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
      )}
      {error && <p className="mt-1.5 text-xs text-red-500">{error}</p>}
    </fieldset>
  );
}
