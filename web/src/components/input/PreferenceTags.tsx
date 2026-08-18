import { PREFERENCE_OPTIONS } from "@/constants/preferences";

interface PreferenceTagsProps {
  value: string[];
  onChange: (tags: string[]) => void;
}

export function PreferenceTags({ value, onChange }: PreferenceTagsProps) {
  function toggle(tag: string) {
    onChange(
      value.includes(tag) ? value.filter((t) => t !== tag) : [...value, tag],
    );
  }

  return (
    <fieldset>
      <legend className="form-label">
        旅行偏好
        <span className="ml-1 font-normal text-sand-400">（可多选）</span>
      </legend>
      <div className="flex flex-wrap gap-2">
        {PREFERENCE_OPTIONS.map((tag) => (
          <button
            key={tag}
            type="button"
            onClick={() => toggle(tag)}
            className={value.includes(tag) ? "tag-active" : "tag-idle"}
          >
            {tag}
          </button>
        ))}
      </div>
    </fieldset>
  );
}
