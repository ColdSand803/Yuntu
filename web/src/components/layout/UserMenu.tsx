import { useState, useRef, useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuthStore } from "@/stores/authStore";

export function UserMenu({ compact = false, hideName = false }: { compact?: boolean; hideName?: boolean }) {
  const navigate = useNavigate();
  const status = useAuthStore((s) => s.status);
  const user = useAuthStore((s) => s.user);
  const quota = useAuthStore((s) => s.quota);
  const activeTrip = useAuthStore((s) => s.activeTrip);
  const logout = useAuthStore((s) => s.logout);

  const [dropdownOpen, setDropdownOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(e.target as Node)
      ) {
        setDropdownOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  if (status !== "authenticated" || !user) {
    return (
      <Link
        to="/login"
        className="rounded-full bg-accent-500 px-4 py-1.5 text-xs font-bold text-white shadow-sm transition-colors hover:bg-accent-600"
      >
        登录 / 注册
      </Link>
    );
  }

  const isReserved = (quota?.reserved ?? 0) > 0 || !!activeTrip;

  const handleLogout = async () => {
    await logout();
    navigate("/", { replace: true });
  };

  const displayName =
    typeof user.display_name === "string" && user.display_name
      ? user.display_name
      : user.masked_email || "用户";
  const avatarChar = ([...displayName][0] || "U").toUpperCase();

  return (
    <div className="flex items-center gap-2.5">
      {/* ⚡ 额度胶囊 */}
      {!compact && (
        <div
          title="公测期免费额度：成功生成扣减 1 次，失败/超时自动退还"
          className={`shadow-xs hidden items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold transition-colors sm:flex ${
            isReserved
              ? "border border-accent-200 bg-accent-50 text-accent-700"
              : quota && quota.remaining > 0
                ? "border border-primary-100 bg-primary-50 text-primary-700"
                : "border border-amber-200 bg-amber-50 text-amber-700"
          }`}
        >
          {isReserved ? (
            <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-accent-400 border-t-accent-600" />
          ) : (
            <span>⚡</span>
          )}
          <span>
            {quota ? `额度 ${quota.remaining}/${quota.limit}` : "额度读取中"}
            {isReserved && (
              <button
                onClick={() =>
                  activeTrip && navigate(`/planning/${activeTrip.job_id}`)
                }
                className="ml-1 underline hover:text-accent-800"
              >
                (规划中...)
              </button>
            )}
          </span>
        </div>
      )}

      {/* 用户下拉菜单 */}
      <div className="relative" ref={dropdownRef}>
        <button
          type="button"
          onClick={() => setDropdownOpen((o) => !o)}
          className="shadow-xs flex items-center gap-1.5 rounded-full border border-gray-200 bg-white/90 px-2.5 py-1 text-xs font-medium text-gray-700 transition-colors hover:bg-gray-50"
        >
          <span className="flex h-5 w-5 items-center justify-center rounded-full bg-primary-100 text-[10px] font-bold text-primary-700">
            {avatarChar}
          </span>
          {!hideName && <span className="hidden md:inline">{displayName}</span>}
          <i
            className={`fas fa-chevron-down text-[9px] text-gray-400 transition-transform ${dropdownOpen ? "rotate-180" : ""}`}
          />
        </button>

        {dropdownOpen && (
          <div className="absolute right-0 z-50 mt-2 w-48 rounded-2xl border border-gray-100 bg-white py-1.5 shadow-xl shadow-gray-900/10">
            <div className="border-b border-gray-50 px-4 py-2">
              <div className="truncate text-xs font-bold text-gray-800">
                {displayName}
              </div>
              {user.masked_email && (
                <div className="truncate font-mono text-[10px] text-gray-400">
                  {user.masked_email}
                </div>
              )}
            </div>
            <Link
              to="/"
              className="flex items-center px-4 py-2 text-xs font-medium text-gray-700 hover:bg-sand-50 hover:text-primary-600 sm:hidden"
            >
              <i className="fa-solid fa-compass mr-2.5 text-gray-400" /> 行程规划
            </Link>
            <Link
              to="/profile"
              className="flex items-center px-4 py-2 text-xs font-medium text-gray-700 hover:bg-sand-50 hover:text-primary-600"
            >
              <i className="fas fa-cog mr-2.5 text-gray-400" /> 个人设置
            </Link>
            <Link
              to="/history"
              className="flex items-center px-4 py-2 text-xs font-medium text-gray-700 hover:bg-sand-50 hover:text-primary-600"
            >
              <i className="fas fa-clock-rotate-left mr-2.5 text-gray-400" />{" "}
              我的行程
            </Link>
            <hr className="my-1 border-gray-100" />
            <button
              type="button"
              onClick={handleLogout}
              className="flex w-full items-center px-4 py-2 text-xs font-medium text-red-600 hover:bg-red-50"
            >
              <i className="fas fa-right-from-bracket mr-2.5 text-red-400" />{" "}
              退出登录
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
