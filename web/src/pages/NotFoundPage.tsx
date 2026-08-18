import { useNavigate } from "react-router-dom";

export default function NotFoundPage() {
  const navigate = useNavigate();

  return (
    <div className="empty-state animate-fade-in">
      <span className="text-6xl">🧭</span>
      <h2 className="font-display text-xl font-bold text-primary-800">
        迷路了？
      </h2>
      <p className="empty-state-text">找不到你要访问的页面</p>
      <button onClick={() => navigate("/")} className="btn-primary mt-3">
        回到首页
      </button>
    </div>
  );
}
