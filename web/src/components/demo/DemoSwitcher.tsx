import { useNavigate, useLocation } from "react-router-dom";

export function DemoSwitcher() {
  const navigate = useNavigate();
  const location = useLocation();
  const path = location.pathname;

  const demos = [
    { id: "capsule", label: "首页·全屏灵感岛", path: "/demo/input-capsule", icon: "fa-compass" },
    { id: "planning", label: "等待页·流光登机牌", path: "/demo/planning", icon: "fa-ticket" },
  ];

  return (
    <aside
      aria-label="Demo方案切换栏"
      className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 flex items-center gap-1.5 p-1.5 rounded-full bg-gray-900/85 text-white shadow-2xl backdrop-blur-xl border border-white/15 text-xs max-w-[95vw] overflow-x-auto"
    >
      <button
        type="button"
        onClick={() => navigate("/")}
        className="px-3 py-1.5 rounded-full text-gray-300 hover:text-white hover:bg-white/10 transition-colors flex items-center gap-1 shrink-0"
      >
        <i className="fa-solid fa-arrow-left text-[10px]" />
        <span>原版首页</span>
      </button>

      <div className="h-4 w-px bg-white/20 mx-0.5 shrink-0" aria-hidden="true" />

      {demos.map((d) => {
        const isActive = path === d.path;
        return (
          <button
            key={d.id}
            type="button"
            onClick={() => navigate(d.path)}
            className={`px-3 py-1.5 rounded-full font-medium transition-all flex items-center gap-1.5 shrink-0 ${
              isActive
                ? "bg-primary-500 text-white font-bold shadow-md shadow-primary-500/30 scale-105"
                : "text-gray-300 hover:text-white hover:bg-white/10"
            }`}
          >
            <i className={`fa-solid ${d.icon} text-[10px]`} />
            <span>{d.label}</span>
          </button>
        );
      })}
    </aside>
  );
}
