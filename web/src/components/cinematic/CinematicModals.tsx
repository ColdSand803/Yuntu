import { useEffect, useState } from "react";
import { X } from "lucide-react";

interface AccommodationModalProps {
  initialValue: string;
  isOpen: boolean;
  onClose: () => void;
  onSave: (value: string) => void;
}

export function CinematicAccommodationModal({
  initialValue,
  isOpen,
  onClose,
  onSave,
}: AccommodationModalProps) {
  const [value, setValue] = useState(initialValue);

  useEffect(() => {
    setValue(initialValue);
  }, [initialValue, isOpen]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isOpen) {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const trimmed = value.trim();
  const handleSave = () => {
    onSave(trimmed.slice(0, 160));
    onClose();
  };

  return (
    <div className="cmp-modal-overlay" role="dialog" aria-modal="true" aria-labelledby="acc-title">
      <div className="cmp-modal">
        <div className="cmp-modal-header">
          <h3 id="acc-title">填写期望住宿</h3>
          <button type="button" aria-label="关闭" onClick={onClose}>
            <X size={18} />
          </button>
        </div>
        <div className="cmp-modal-body">
          <label htmlFor="acc-input">酒店 / 民宿名称或意向商圈（选填）</label>
          <input
            id="acc-input"
            type="text"
            maxLength={160}
            autoFocus
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="例如：解放碑附近、大理古城南门民宿"
          />
          <div className="cmp-modal-char-count">{value.length}/160</div>
        </div>
        <div className="cmp-modal-footer">
          <button type="button" className="cmp-text-button" onClick={onClose}>
            取消
          </button>
          <button type="button" className="cmp-modal-save-btn" onClick={handleSave}>
            保存
          </button>
        </div>
      </div>
    </div>
  );
}

interface NotesModalProps {
  initialNotes: string;
  initialFromCity: string;
  isOpen: boolean;
  onClose: () => void;
  onSave: (notes: string, fromCity: string) => void;
}

export function CinematicNotesModal({
  initialNotes,
  initialFromCity,
  isOpen,
  onClose,
  onSave,
}: NotesModalProps) {
  const [notes, setNotes] = useState(initialNotes);
  const [fromCity, setFromCity] = useState(initialFromCity);

  useEffect(() => {
    setNotes(initialNotes);
    setFromCity(initialFromCity);
  }, [initialNotes, initialFromCity, isOpen]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isOpen) {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const handleSave = () => {
    onSave(notes.trim().slice(0, 200), fromCity.trim().slice(0, 10));
    onClose();
  };

  return (
    <div className="cmp-modal-overlay" role="dialog" aria-modal="true" aria-labelledby="notes-title">
      <div className="cmp-modal">
        <div className="cmp-modal-header">
          <h3 id="notes-title">补充要求与出发城市</h3>
          <button type="button" aria-label="关闭" onClick={onClose}>
            <X size={18} />
          </button>
        </div>
        <div className="cmp-modal-body">
          <div>
            <label htmlFor="from-city-input">出发城市（选填，最多10字）</label>
            <input
              id="from-city-input"
              type="text"
              maxLength={10}
              value={fromCity}
              onChange={(e) => setFromCity(e.target.value)}
              placeholder="例如：北京、上海"
            />
          </div>
          <div>
            <label htmlFor="notes-textarea">其他特殊需求或备注（选填，最多200字）</label>
            <textarea
              id="notes-textarea"
              rows={3}
              maxLength={200}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="例如：喜欢安静的咖啡馆、不吃辣、希望行程不要太赶"
            />
            <div className="cmp-modal-char-count">{notes.length}/200</div>
          </div>
        </div>
        <div className="cmp-modal-footer">
          <button type="button" className="cmp-text-button" onClick={onClose}>
            取消
          </button>
          <button type="button" className="cmp-modal-save-btn" onClick={handleSave}>
            保存
          </button>
        </div>
      </div>
    </div>
  );
}
