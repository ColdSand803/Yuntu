interface CloudBackgroundProps {
  intensity?: "light" | "medium" | "strong";
}

export function CloudBackground({ intensity = "medium" }: CloudBackgroundProps) {
  const opacity = intensity === "light" ? "opacity-20" : intensity === "strong" ? "opacity-40" : "opacity-30";

  return (
    <div className={`pointer-events-none fixed inset-0 -z-10 overflow-hidden ${opacity}`} aria-hidden="true">
      <div className="absolute -right-32 -top-32 h-[500px] w-[500px] animate-cloud-drift rounded-full bg-gradient-to-br from-primary-200/60 to-primary-100/30 blur-3xl" />
      <div className="absolute -left-24 top-1/3 h-[400px] w-[400px] animate-cloud-drift-slow rounded-full bg-gradient-to-tr from-accent-100/40 to-primary-100/20 blur-3xl" />
      <div className="absolute -right-16 bottom-1/4 h-[350px] w-[350px] animate-cloud-drift rounded-full bg-gradient-to-bl from-primary-100/50 to-transparent blur-3xl" />
    </div>
  );
}
