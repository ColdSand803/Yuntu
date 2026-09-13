import { useState, useRef, useEffect, type ReactNode } from "react";
import { ChevronDown, Check } from "lucide-react";
import { useId } from "react";

export interface SelectOption<T extends string | number = string> {
  value: T;
  label: string;
  description?: string;
  icon?: ReactNode;
  disabled?: boolean;
}

export interface SelectProps<T extends string | number = string> {
  options: SelectOption<T>[];
  value: T;
  onChange: (value: T) => void;
  label?: string;
  placeholder?: string;
  disabled?: boolean;
  className?: string;
  size?: "sm" | "md" | "lg";
  error?: string;
}

export function Select<T extends string | number = string>({
  options,
  value,
  onChange,
  label,
  placeholder = "请选择...",
  disabled = false,
  className = "",
  size = "md",
  error,
}: SelectProps<T>) {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const triggerId = useId();

  const selectedOption = options.find((opt) => opt.value === value);

  // Close when clicking outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    if (isOpen) {
      document.addEventListener("mousedown", handleClickOutside);
    }
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [isOpen]);

  // Keyboard navigation
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (!isOpen) return;
      if (e.key === "Escape") {
        setIsOpen(false);
      } else if (e.key === "ArrowDown") {
        e.preventDefault();
        const currentIndex = options.findIndex((opt) => opt.value === value);
        const nextIndex = (currentIndex + 1) % options.length;
        if (!options[nextIndex].disabled) {
          onChange(options[nextIndex].value);
        }
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        const currentIndex = options.findIndex((opt) => opt.value === value);
        const prevIndex = (currentIndex - 1 + options.length) % options.length;
        if (!options[prevIndex].disabled) {
          onChange(options[prevIndex].value);
        }
      } else if (e.key === "Enter") {
        e.preventDefault();
        setIsOpen(false);
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, options, value, onChange]);

  const sizeClasses = {
    sm: "px-3 py-1.5 text-xs rounded-lg",
    md: "px-3.5 py-2 text-xs sm:text-sm rounded-xl",
    lg: "px-4 py-2.5 text-sm sm:text-base rounded-xl",
  }[size];

  return (
    <div className={`relative w-full ${className}`} ref={containerRef}>
      {label && (
        <label
          htmlFor={triggerId}
          className="block text-xs font-bold text-gray-700 mb-1.5"
        >
          {label}
        </label>
      )}

      {/* Trigger Button */}
      <button
        id={triggerId}
        type="button"
        disabled={disabled}
        onClick={() => !disabled && setIsOpen(!isOpen)}
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        className={`w-full flex items-center justify-between gap-2 border bg-white font-medium text-left transition-all duration-150 ${sizeClasses} ${
          error
            ? "border-red-300 ring-2 ring-red-100"
            : isOpen
              ? "border-primary-500 ring-2 ring-primary-100 shadow-sm"
              : "border-sand-300 hover:border-sand-400 hover:bg-sand-50/40"
        } ${disabled ? "opacity-50 cursor-not-allowed bg-sand-100/50" : "cursor-pointer"}`}
      >
        <div className="flex items-center gap-2 truncate">
          {selectedOption?.icon && (
            <span className="shrink-0 text-gray-500">{selectedOption.icon}</span>
          )}
          <span className={`truncate ${selectedOption ? "text-gray-900 font-semibold" : "text-gray-400 font-normal"}`}>
            {selectedOption ? selectedOption.label : placeholder}
          </span>
        </div>

        <ChevronDown
          size={11}
          className={`text-gray-400 shrink-0 transition-transform duration-200 ${
            isOpen ? "rotate-180 text-primary-600" : ""
          }`}
        />
      </button>

      {/* Dropdown Menu */}
      {isOpen && (
        <div
          role="listbox"
          className="absolute z-50 mt-1.5 w-full rounded-xl border border-sand-200 bg-white/95 backdrop-blur-md p-1 shadow-lg shadow-gray-900/5 focus:outline-none animate-in fade-in zoom-in-95 duration-100"
        >
          <div className="max-h-60 overflow-y-auto space-y-0.5 custom-scrollbar">
            {options.map((option) => {
              const isSelected = option.value === value;
              return (
                <button
                  key={String(option.value)}
                  type="button"
                  role="option"
                  aria-selected={isSelected}
                  disabled={option.disabled}
                  onClick={() => {
                    if (!option.disabled) {
                      onChange(option.value);
                      setIsOpen(false);
                    }
                  }}
                  className={`w-full flex items-center justify-between gap-2 rounded-lg px-3 py-2 text-left text-xs sm:text-sm transition-colors ${
                    isSelected
                      ? "bg-primary-50 text-primary-900 font-bold"
                      : option.disabled
                        ? "opacity-40 cursor-not-allowed text-gray-400"
                        : "text-gray-700 hover:bg-sand-100 hover:text-gray-900"
                  }`}
                >
                  <div className="flex items-center gap-2 truncate">
                    {option.icon && (
                      <span className="shrink-0">{option.icon}</span>
                    )}
                    <div>
                      <div className="truncate">{option.label}</div>
                      {option.description && (
                        <div className="text-[11px] text-gray-400 font-normal mt-0.5">
                          {option.description}
                        </div>
                      )}
                    </div>
                  </div>

                  {isSelected && (
                    <Check size={12} className="text-primary-600 shrink-0" />
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {error && <p className="mt-1 text-xs text-red-600">{error}</p>}
    </div>
  );
}
