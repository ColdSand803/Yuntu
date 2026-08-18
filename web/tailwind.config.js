/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        primary: {
          50: "#eef9f7",
          100: "#d2efeb",
          200: "#a7ded7",
          300: "#6ec6bb",
          400: "#1d9e91",
          500: "#0f766e",
          600: "#0c625b",
          700: "#0a4f49",
          800: "#073d39",
          900: "#052b28",
        },
        accent: {
          50: "#fff7ed",
          100: "#ffedd5",
          200: "#fed7aa",
          300: "#fdba74",
          400: "#fb923c",
          500: "#f97316",
          600: "#ea580c",
          700: "#c2410c",
          800: "#9a3412",
          900: "#7c2d12",
        },
        sand: {
          50: "#f9fafb",
          100: "#f3f4f6",
          200: "#e5e7eb",
          300: "#d1d5db",
          400: "#9ca3af",
          500: "#6b7280",
        },
      },
      maxWidth: {
        form: "34rem",
      },
      borderRadius: {
        xl: "16px",
        "2xl": "20px",
      },
      boxShadow: {
        soft: "0 2px 16px -2px rgba(15, 118, 110, 0.08)",
        card: "0 4px 24px -4px rgba(15, 118, 110, 0.10)",
        "card-hover": "0 8px 32px -4px rgba(15, 118, 110, 0.15)",
      },
      fontFamily: {
        display: ['"Satoshi"', "system-ui", '"Noto Sans SC"', "sans-serif"],
        body: ["system-ui", '"Noto Sans SC"', "sans-serif"],
      },
    },
  },
  plugins: [],
};
