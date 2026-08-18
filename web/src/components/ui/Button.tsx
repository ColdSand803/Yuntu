import type { ButtonHTMLAttributes, ReactNode } from "react";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "outline" | "ghost" | "danger";
  size?: "sm" | "md" | "lg";
  loading?: boolean;
  icon?: ReactNode;
}

export function Button({
  children,
  variant = "primary",
  size = "md",
  loading = false,
  icon,
  disabled,
  className = "",
  ...props
}: ButtonProps) {
  const baseClasses =
    "inline-flex items-center justify-center font-semibold transition-all duration-150 active:scale-[0.98] disabled:opacity-50 disabled:pointer-events-none disabled:active:scale-100";

  const sizeClasses = {
    sm: "px-3 py-1.5 text-xs rounded-lg gap-1.5",
    md: "px-4 py-2 text-xs sm:text-sm rounded-xl gap-2",
    lg: "px-5 py-2.5 text-sm sm:text-base rounded-xl gap-2.5",
  }[size];

  const variantClasses = {
    primary:
      "bg-primary-600 text-white shadow-sm hover:bg-primary-700 active:bg-primary-800",
    secondary:
      "bg-sand-100 text-gray-800 hover:bg-sand-200 active:bg-sand-300",
    outline:
      "border border-sand-300 bg-white text-gray-700 hover:bg-sand-50 hover:border-sand-400 active:bg-sand-100",
    ghost:
      "bg-transparent text-gray-600 hover:bg-sand-100 hover:text-gray-900 active:bg-sand-200",
    danger:
      "border border-red-200 bg-red-50 text-red-600 hover:bg-red-100 active:bg-red-200",
  }[variant];

  return (
    <button
      disabled={disabled || loading}
      className={`${baseClasses} ${sizeClasses} ${variantClasses} ${className}`}
      {...props}
    >
      {loading ? (
        <i className="fa-solid fa-circle-notch animate-spin text-xs" />
      ) : (
        icon
      )}
      {children}
    </button>
  );
}
