interface NotesInputProps {
  value: string;
  onChange: (notes: string) => void;
}

const MAX_LENGTH = 200;

export function NotesInput({ value, onChange }: NotesInputProps) {
  return (
    <fieldset>
      <legend className="form-label">补充需求</legend>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value.slice(0, MAX_LENGTH))}
        placeholder="例如：想多逛老街、第一天下午才到、不吃辣..."
        rows={3}
        className="w-full resize-none rounded-xl border border-primary-100 bg-white px-4 py-3 text-sm text-primary-900 placeholder:text-sand-400 focus:border-primary-400 focus:outline-none focus:ring-2 focus:ring-primary-100"
      />
      <p className="mt-1 text-right text-xs text-sand-400">
        {value.length}/{MAX_LENGTH}
      </p>
    </fieldset>
  );
}
