import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuthStore } from "@/stores/authStore";
import { UserMenu } from "./UserMenu";

export default function Header() {
  const location = useLocation();
  const navigate = useNavigate();
  const onHome = location.pathname === "/";
  const status = useAuthStore((s) => s.status);
  const user = useAuthStore((s) => s.user);
  const quota = useAuthStore((s) => s.quota);
  const activeTrip = useAuthStore((s) => s.activeTrip);
  const logout = useAuthStore((s) => s.logout);

  const [drawerOpen, setDrawerOpen] = useState(false);

  const handleLogout = async () => {
    await logout();
    navigate("/", { replace: true });
  };

  return (
    <header className="fixed left-0 right-0 top-0 z-50 border-b border-gray-100 bg-white/80 backdrop-blur-md">
      <div className="flex w-full items-center justify-between px-5 py-2.5 sm:px-10 lg:px-14">
        {/* Left: Logo & Nav */}
        <div className="flex items-center space-x-8">
          <Link to="/" className="flex items-center space-x-2">
            <img src="/logo.svg" alt="云途 YunTu" className="h-9 w-9" />
            <span className="text-2xl font-bold tracking-tight text-gray-800">
              云途 <span className="font-normal text-primary-500">YunTu</span>
            </span>
          </Link>

          <nav className="hidden items-center space-x-6 font-medium text-gray-600 lg:flex">
            <Link
              to="/"
              className={
                onHome
                  ? "border-b-2 border-primary-500 pb-1 text-primary-500"
                  : "transition-colors hover:text-gray-900"
              }
            >
              行程规划
            </Link>
            {status === "authenticated" && (
              <Link
                to="/history"
                className={
                  location.pathname === "/history"
                    ? "border-b-2 border-primary-500 pb-1 text-primary-500"
                    : "transition-colors hover:text-gray-900"
                }
              >
                我的行程
              </Link>
            )}
          </nav>
        </div>

        {/* Right: Auth & Quota */}
        <div className="hidden items-center space-x-4 lg:flex">
          <UserMenu />
        </div>

        {/* Mobile Hamburger */}
        <div className="flex items-center lg:hidden">
          {status === "authenticated" && (
            <div className="mr-3 flex items-center gap-1 rounded-full border border-primary-100 bg-primary-50 px-2.5 py-1 text-xs font-medium text-primary-700">
              ⚡ {quota ? `${quota.remaining}/${quota.limit}` : "额度读取中"}
            </div>
          )}
          <button
            type="button"
            onClick={() => setDrawerOpen((o) => !o)}
            aria-label="切换菜单"
            className="flex h-9 w-9 items-center justify-center rounded-xl border border-gray-200 text-gray-600 hover:bg-gray-50"
          >
            <i className={`fas ${drawerOpen ? "fa-xmark" : "fa-bars"}`} />
          </button>
        </div>
      </div>

      {/* Mobile Drawer */}
      {drawerOpen && (
        <div className="border-t border-gray-100 bg-white px-6 py-4 lg:hidden">
          <nav className="flex flex-col space-y-3 text-sm font-medium text-gray-700">
            <Link to="/" className="py-1 hover:text-primary-600">
              行程规划
            </Link>
            {status === "authenticated" ? (
              <>
                <Link to="/history" className="py-1 hover:text-primary-600">
                  我的行程
                </Link>
                <Link to="/profile" className="py-1 hover:text-primary-600">
                  个人设置
                  {user?.masked_email
                    ? ` (${user.masked_email})`
                    : user?.linux_do_username
                      ? ` (@${user.linux_do_username})`
                      : user?.display_name
                        ? ` (${user.display_name})`
                        : ""}
                </Link>
                {activeTrip && (
                  <Link
                    to={`/planning/${activeTrip.job_id}`}
                    className="flex items-center gap-2 rounded-xl bg-accent-50 p-2.5 text-xs text-accent-700"
                  >
                    <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-accent-400 border-t-accent-600" />
                    返回当前正在规划的行程
                  </Link>
                )}
                <button
                  type="button"
                  onClick={handleLogout}
                  className="pt-2 text-left text-xs font-semibold text-red-600"
                >
                  退出登录
                </button>
              </>
            ) : (
              <Link
                to="/login"
                className="mt-2 inline-block rounded-xl bg-accent-500 py-2.5 text-center font-bold text-white"
              >
                登录 / 注册
              </Link>
            )}
          </nav>
        </div>
      )}
    </header>
  );
}
