/** Floating gradient orbs for brand atmosphere. Place as a sibling inside a relative container. */
export function CloudDecor({ intensity = "normal" }: { intensity?: "light" | "normal" | "strong" }) {
  const opacity = intensity === "strong" ? "opacity-40" : intensity === "light" ? "opacity-15" : "opacity-25";
  return (
    <div className="pointer-events-none absolute inset-0 -z-10 overflow-hidden" aria-hidden="true">
      <div
        className={`absolute -left-32 -top-20 h-[420px] w-[420px] rounded-full bg-primary-200 blur-[100px] ${opacity}`}
        style={{ animation: "cloudDrift 20s ease-in-out infinite alternate" }}
      />
      <div
        className={`absolute -right-24 top-1/3 h-[320px] w-[320px] rounded-full bg-accent-200 blur-[90px] ${opacity}`}
        style={{ animation: "cloudDrift 25s ease-in-out infinite alternate-reverse" }}
      />
      <div
        className={`absolute bottom-0 left-1/3 h-[280px] w-[280px] rounded-full bg-primary-100 blur-[80px] ${opacity}`}
        style={{ animation: "cloudDrift 22s ease-in-out infinite alternate" }}
      />
    </div>
  );
}
