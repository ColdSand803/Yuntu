import { Link, useLocation } from "react-router-dom";

export default function Header() {
  const location = useLocation();
  const onHome = location.pathname === "/";

  return (
    <header className="fixed left-0 right-0 top-0 z-50 border-b border-gray-100 bg-white/80 backdrop-blur-md">
      <div className="flex w-full items-center justify-between px-5 py-2.5 sm:px-10 lg:px-14">
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
          </nav>
        </div>
      </div>
    </header>
  );
}
