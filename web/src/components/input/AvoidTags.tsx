import { AVOID_OPTIONS } from "@/constants/preferences";

interface AvoidTagsProps {
  value: string[];
  onChange: (tags: string[]) => void;
}

export function AvoidTags({ value, onChange }: AvoidTagsProps) {
  function toggle(tag: string) {
    onChange(
      value.includes(tag) ? value.filter((t) => t !== tag) : [...value, tag],
    );
  }

  return (
    <fieldset>
      <legend className="form-label">
        希望避开
        <span className="ml-1 font-normal text-sand-400">（可多选）</span>
      </legend>
      <div className="flex flex-wrap gap-2">
        {AVOID_OPTIONS.map((tag) => (
          <button
            key={tag}
            type="button"
            onClick={() => toggle(tag)}
            className={`rounded-full border px-3.5 py-1.5 text-sm transition-all duration-150 ${
              value.includes(tag)
                ? "border-red-400 bg-red-50 text-red-600"
                : "tag-idle"
            }`}
          >
            {tag}
          </button>
        ))}
      </div>
    </fieldset>
  );
}
