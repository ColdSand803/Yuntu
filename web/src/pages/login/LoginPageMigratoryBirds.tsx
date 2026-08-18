import { useState, useEffect, useRef, useMemo, useCallback } from "react";
import { useNavigate, useSearchParams, Link } from "react-router-dom";
import { sendEmailCode, verifyEmailCode, buildLinuxDoStartUrl, ApiRequestError } from "@/services/api";
import { useAuthStore, broadcastAuthEvent } from "@/stores/authStore";
import { sanitizeReturnTo } from "@/utils/url";
import { MigratoryBirdsCanvas } from "../../components/common/MigratoryBirdsCanvas";
import { Card3D } from "../../components/common/Card3D";
import { resolveCityAssetVariant } from "@/config/cityAssets";
import type { AuthMode } from "@/types/auth";

const PAPER_NOISE_SVG =
  "url(\"data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='4' stitchTiles='stitch'/%3E%3CfeColorMatrix type='saturate' values='0'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.55'/%3E%3C/svg%3E\")";

// 项目 10 大热门旅游城市真实美图源
const ALL_CITY_PLAYLIST: Array<{ city: string; pinyin: string; epithet: string; img: string }> = [
  { city: '杭州', pinyin: 'HANGZHOU', epithet: '烟雨江南 · 西子湖畔', img: '/city/hangzhou/luobing-egNgMn5CS18-unsplash.jpg' },
  { city: '杭州', pinyin: 'HANGZHOU', epithet: '烟雨江南 · 西子湖畔', img: '/city/hangzhou/ming-han-low-5UjoDKlGETs-unsplash.jpg' },
  { city: '北京', pinyin: 'BEIJING', epithet: '千年古都 · 皇家气韵', img: '/city/beijing/hanson-lu-_8EFj6ISA08-unsplash.jpg' },
  { city: '北京', pinyin: 'BEIJING', epithet: '千年古都 · 皇家气韵', img: '/city/beijing/victor-he-0xn9T2cEigE-unsplash.jpg' },
  { city: '上海', pinyin: 'SHANGHAI', epithet: '摩登海派 · 璀璨江景', img: '/city/shanghai/freeman-zhou-oV9hp8wXkPE-unsplash.jpg' },
  { city: '重庆', pinyin: 'CHONGQING', epithet: '立体山城 · 赛博夜景', img: '/city/chongqing/harrison-qi-E9dIbdSd7LU-unsplash.jpg' },
  { city: '成都', pinyin: 'CHENGDU', epithet: '天府之国 · 慢享生活', img: '/city/chengdu/bamboo-joe-EoVw0eEM4lQ-unsplash.jpg' },
  { city: '西安', pinyin: 'XI\'AN', epithet: '十三朝古都 · 丝路起点', img: '/city/xian/aoyu-zhang-KNpElyP6R20-unsplash.jpg' },
  { city: '南京', pinyin: 'NANJING', epithet: '六朝古都 · 金陵风雅', img: '/city/nanjing/jennifer-chen-Pnc2Uxb7PG0-unsplash.jpg' },
  { city: '长沙', pinyin: 'CHANGSHA', epithet: '星城烟火 · 时尚长歌', img: '/city/changsha/zhe-zhang-TCaefwd87wE-unsplash.jpg' },
  { city: '青岛', pinyin: 'QINGDAO', epithet: '红瓦绿树 · 碧海蓝天', img: '/city/qingdao/r-hai-BZrJ5tcuJE0-unsplash.jpg' },
  { city: '桂林', pinyin: 'GUILIN', epithet: '山水甲天下 · 漓江美景', img: '/city/guilin/jingyixiu-wmlj2DfZDkA-unsplash.jpg' },
];

/* ---------- 模式独立的验证码挑战状态 ---------- */

/** 发送验证码时的快照，用于提交时校验一致性 */
interface ChallengeSnapshot {
  challengeId: string;
  email: string;
  invitationCode: string | null; // 仅注册模式有值
  resendAvailableAt: number;     // 绝对时间戳 ms
}

/** 每个模式的完整状态 */
interface ModeState {
  challenge: ChallengeSnapshot | null;
  code: string;
}

function createEmptyModeStates(): Record<AuthMode, ModeState> {
  return {
    login: { challenge: null, code: "" },
    register: { challenge: null, code: "" },
  };
}

/** 从 resendAvailableAt 计算剩余秒数 */
function calcCountdown(resendAvailableAt: number | undefined): number {
  if (!resendAvailableAt) return 0;
  return Math.max(0, Math.ceil((resendAvailableAt - Date.now()) / 1000));
}

export default function LoginPageMigratoryBirds() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const returnTo = sanitizeReturnTo(searchParams.get("returnTo"));

  const authStatus = useAuthStore((s) => s.status);
  const bootstrap = useAuthStore((s) => s.bootstrap);

  const [mode, setMode] = useState<AuthMode>("login");
  const [email, setEmail] = useState("");
  const [invitationCode, setInvitationCode] = useState("");

  // 模式独立的验证码挑战状态（内存，不持久化）
  const modeStatesRef = useRef<Record<AuthMode, ModeState>>(createEmptyModeStates());

  // 当前模式的渲染状态（从 modeStatesRef 同步）
  const [currentChallenge, setCurrentChallenge] = useState<ChallengeSnapshot | null>(null);
  const [currentCode, setCurrentCode] = useState("");
  const [countdown, setCountdown] = useState(0);

  const [sending, setSending] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [linuxDoLoading, setLinuxDoLoading] = useState(false);

  const handleLinuxDoLogin = () => {
    if (linuxDoLoading) return;
    setLinuxDoLoading(true);
    const startUrl = buildLinuxDoStartUrl(returnTo);
    window.location.assign(startUrl);
  };

  const [emailError, setEmailError] = useState<string | null>(null);
  const [invitationError, setInvitationError] = useState<string | null>(null);
  const [otpError, setOtpError] = useState<string | null>(null);
  const [infoNotice, setInfoNotice] = useState<string | null>(null);

  // 10 大城市全量平滑渐变轮播
  const [playlistIndex, setPlaylistIndex] = useState(0);
  const [cameraX, setCameraX] = useState(0);

  const cityPlaylist = useMemo(
    () =>
      ALL_CITY_PLAYLIST.map((item) => ({
        ...item,
        img: resolveCityAssetVariant(item.img, {
          mobile:
            window.matchMedia?.("(max-width: 768px)")?.matches ?? false,
        }),
      })),
    [],
  );
  const currentMedia = useMemo(
    () => cityPlaylist[playlistIndex],
    [cityPlaylist, playlistIndex],
  );

  const otpInputRef = useRef<HTMLInputElement>(null);
  const invitationInputRef = useRef<HTMLInputElement>(null);

  // 每 6 秒自动平滑更换城市大图
  useEffect(() => {
    const timer = setInterval(() => {
      setPlaylistIndex((prev) => (prev + 1) % cityPlaylist.length);
    }, 6000);
    return () => clearInterval(timer);
  }, [cityPlaylist.length]);

  useEffect(() => {
    if (authStatus === "authenticated") {
      navigate(returnTo, { replace: true });
    }
  }, [authStatus, navigate, returnTo]);

  // 基于绝对时间戳的倒计时，同一邮箱跨模式共享发送冷却
  useEffect(() => {
    const trimmedEmail = email.trim();
    // 查找同一邮箱在所有模式中最晚的 resendAvailableAt
    let latestResendAt = 0;
    for (const m of ["login", "register"] as AuthMode[]) {
      const ch = modeStatesRef.current[m].challenge;
      if (ch && ch.email === trimmedEmail && ch.resendAvailableAt > latestResendAt) {
        latestResendAt = ch.resendAvailableAt;
      }
    }
    // currentChallenge 可能比 ref 更新（刚发送完码还未同步到 ref）
    if (currentChallenge && currentChallenge.email === trimmedEmail && currentChallenge.resendAvailableAt > latestResendAt) {
      latestResendAt = currentChallenge.resendAvailableAt;
    }

    if (!latestResendAt || calcCountdown(latestResendAt) <= 0) {
      setCountdown(0);
      return;
    }
    setCountdown(calcCountdown(latestResendAt));
    const timer = setInterval(() => {
      const remaining = calcCountdown(latestResendAt);
      setCountdown(remaining);
      if (remaining <= 0) clearInterval(timer);
    }, 1000);
    return () => clearInterval(timer);
  }, [currentChallenge, email, mode]);

  /** 将当前 UI 状态同步回 modeStatesRef */
  const saveCurrentModeState = useCallback(() => {
    modeStatesRef.current[mode] = {
      challenge: currentChallenge,
      code: currentCode,
    };
  }, [mode, currentChallenge, currentCode]);

  /** 从 modeStatesRef 恢复目标模式的状态到 UI */
  const restoreModeState = useCallback((targetMode: AuthMode) => {
    const state = modeStatesRef.current[targetMode];
    setCurrentChallenge(state.challenge);
    setCurrentCode(state.code);
  }, []);

  /** 使指定模式的 challenge 失效 */
  const invalidateChallenge = useCallback((targetMode: AuthMode) => {
    modeStatesRef.current[targetMode] = {
      ...modeStatesRef.current[targetMode],
      challenge: null,
      code: "",
    };
    // 如果失效的是当前模式，同步到 UI
    if (targetMode === mode) {
      setCurrentChallenge(null);
      setCurrentCode("");
    }
  }, [mode]);

  const handleTabSwitch = (targetMode: AuthMode) => {
    if (targetMode === mode) return;
    // 保存当前模式的状态
    saveCurrentModeState();
    // 切换模式
    setMode(targetMode);
    // 从目标模式恢复状态
    restoreModeState(targetMode);
    // 清除临时错误/提示（不清除验证码挑战）
    setOtpError(null);
    setInfoNotice(null);
    setEmailError(null);
    setInvitationError(null);
  };

  const handleEmailChange = (newEmail: string) => {
    setEmail(newEmail);
    const trimmed = newEmail.trim();
    // 邮箱变化时，使所有与旧邮箱绑定的挑战失效
    for (const m of ["login", "register"] as AuthMode[]) {
      const ch = modeStatesRef.current[m].challenge;
      if (ch && ch.email !== trimmed) {
        invalidateChallenge(m);
      }
    }
  };

  const handleInvitationCodeChange = (newCode: string) => {
    setInvitationCode(newCode);
    const trimmed = newCode.trim();
    // 邀请码变化时，仅使注册挑战失效
    const regChallenge = modeStatesRef.current.register.challenge;
    if (regChallenge && regChallenge.invitationCode !== trimmed) {
      invalidateChallenge("register");
    }
  };

  const handleCodeChange = (newCode: string) => {
    const sanitized = newCode.replace(/\D/g, "");
    setCurrentCode(sanitized);
    modeStatesRef.current[mode] = {
      ...modeStatesRef.current[mode],
      code: sanitized,
    };
  };

  const handleSendCode = async () => {
    if (sending || countdown > 0) return;
    setEmailError(null);
    setInvitationError(null);
    setOtpError(null);
    setInfoNotice(null);

    const cleanEmail = email.trim();
    if (!cleanEmail || !cleanEmail.includes("@")) {
      setEmailError("请输入有效的邮箱地址");
      return;
    }

    if (mode === "register" && !invitationCode.trim()) {
      setInvitationError("请输入邀请码");
      invitationInputRef.current?.focus();
      return;
    }

    // 捕获请求发起时的模式，防止切换标签后响应写入错误模式
    const requestMode = mode;
    const requestEmail = cleanEmail;
    const requestInvCode = mode === "register" ? invitationCode.trim() : null;

    setSending(true);
    try {
      const res = await sendEmailCode(
        requestMode,
        requestEmail,
        requestMode === "register" ? requestInvCode : null,
      );

      const snapshot: ChallengeSnapshot = {
        challengeId: res.challenge_id,
        email: requestEmail,
        invitationCode: requestInvCode,
        resendAvailableAt: Date.now() + (res.resend_after_seconds || 60) * 1000,
      };

      // 写入发起请求时的模式（而非当前模式）
      modeStatesRef.current[requestMode] = {
        ...modeStatesRef.current[requestMode],
        challenge: snapshot,
      };

      // 仅当请求发起时的模式仍是当前模式时，更新 UI 渲染状态
      if (requestMode === mode) {
        setCurrentChallenge(snapshot);
        if (import.meta.env.VITE_USE_MOCK === "true") {
          const mockCode = "123456";
          setCurrentCode(mockCode);
          modeStatesRef.current[requestMode].code = mockCode;
          setInfoNotice("验证码已发送（测试环境自动回填：123456）");
        } else {
          setCurrentCode("");
          modeStatesRef.current[requestMode].code = "";
          setInfoNotice("验证码已发送至你的邮箱，请在 10 分钟内查收。");
        }
        setTimeout(() => otpInputRef.current?.focus(), 100);
      }
      // 如果已经切换了标签，challenge 已存储到 modeStatesRef 中，
      // 切回时会自动恢复
    } catch (err: unknown) {
      // 仅当请求模式仍为当前模式时显示错误
      if (requestMode === mode) {
        if (err instanceof ApiRequestError) {
          if (err.code === "INVITATION_INVALID" || err.code === "INVITATION_EXHAUSTED") {
            setInvitationError(err.message || "邀请码无效或已超限");
            invitationInputRef.current?.focus();
          } else if (err.code === "INVALID_EMAIL" || err.code === "EMAIL_FORMAT_INVALID") {
            setEmailError(err.message || "邮箱格式不正确");
          } else {
            setOtpError(err.message || "验证码发送失败");
          }
        } else {
          setOtpError("发送失败，请检查网络设置");
        }
      }
    } finally {
      setSending(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (verifying) return;
    setOtpError(null);
    setInfoNotice(null);

    if (!currentChallenge) {
      setOtpError("请先获取邮箱验证码");
      return;
    }

    // 校验当前状态与发送验证码时的快照一致
    const cleanEmail = email.trim();
    if (currentChallenge.email !== cleanEmail) {
      setOtpError("邮箱已变更，请重新获取验证码");
      invalidateChallenge(mode);
      return;
    }
    if (mode === "register" && currentChallenge.invitationCode !== invitationCode.trim()) {
      setOtpError("邀请码已变更，请重新获取验证码");
      invalidateChallenge("register");
      return;
    }

    const cleanCode = currentCode.trim();
    if (!cleanCode || cleanCode.length !== 6 || !/^\d{6}$/.test(cleanCode)) {
      setOtpError("请输入 6 位数字验证码");
      otpInputRef.current?.focus();
      return;
    }

    setVerifying(true);
    try {
      await verifyEmailCode(currentChallenge.challengeId, cleanCode);
      await bootstrap();
      broadcastAuthEvent("LOGIN");
      navigate(returnTo, { replace: true });
    } catch (err: unknown) {
      if (err instanceof ApiRequestError) {
        if (err.status === 409 && err.code === "REGISTRATION_REQUIRED") {
          setMode("register");
          invalidateChallenge("login");
          setInfoNotice("该邮箱尚未注册，已自动切至注册模式。");
        } else if (err.status === 409 && err.code === "LOGIN_REQUIRED") {
          setMode("login");
          invalidateChallenge("register");
          setInfoNotice("该邮箱已注册，已自动切至登录模式。");
        } else if (err.code === "OTP_INVALID" || err.code === "OTP_EXPIRED") {
          setOtpError(err.message || "验证码错误或已失效");
          setCurrentCode("");
          modeStatesRef.current[mode].code = "";
        } else {
          setOtpError(err.message || "验证失败");
        }
      } else {
        setOtpError("验证失败，请检查网络");
      }
    } finally {
      setVerifying(false);
    }
  };

  return (
    <div className="relative flex min-h-screen w-full flex-col bg-[#141210] font-body text-[#2c241c] overflow-hidden select-none">
      {/* 10 大热门旅游城市风光摄影全量平滑轮播背景 */}
      <div className="fixed inset-0 z-0 pointer-events-none overflow-hidden">
        {cityPlaylist.map((item, idx) => (
          <div
            key={`${item.city}-${idx}`}
            className="absolute inset-0 bg-cover bg-center transition-opacity duration-1000 ease-in-out filter brightness-[0.85] contrast-105"
            style={{
              backgroundImage: `url('${item.img}')`,
              opacity: idx === playlistIndex ? 1 : 0,
              transform: `scale(1.2) translateX(${Math.max(-60, Math.min(60, cameraX * 0.1))}px)`,
              willChange: 'transform, opacity',
            }}
          />
        ))}

        {/* 渐变遮罩 + 细致纸质噪点 */}
        <div className="absolute inset-0 bg-gradient-to-t from-black/60 via-black/30 to-black/50" />
        <div
          className="absolute inset-0 opacity-[0.05] mix-blend-multiply"
          style={{
            backgroundImage: PAPER_NOISE_SVG,
            backgroundRepeat: 'repeat',
            backgroundSize: '200px 200px',
          }}
        />
      </div>

      {/* Boids 候鸟迁徙 Canvas 物理引擎 */}
      <MigratoryBirdsCanvas
        interactive={true}
        onPanUpdate={(pan) => setCameraX(pan)}
      />

      {/* 极简高级 Header */}
      <header className="relative z-20 flex h-20 items-center justify-between px-8">
        <Link to="/" className="flex items-center space-x-3">
          <img src="/logo.svg" alt="云途" className="h-7 w-7 drop-shadow-md" />
          <span className="font-serif text-base font-bold tracking-[0.2em] text-white drop-shadow-md leading-none">
            YUNTU TRAVEL
          </span>
        </Link>

        {/* 当前目的地城市标识 (绝对居中于屏幕中轴线，与下方 3D 登录卡片 100% 垂直中轴线精准对齐) */}
        <div className="absolute left-1/2 -translate-x-1/2 flex items-center space-x-2.5 rounded-full bg-black/40 px-4 py-1.5 border border-white/20 shadow-xl backdrop-blur-xl">
          <span className="h-2 w-2 rounded-full bg-amber-400 animate-ping" />
          <span className="font-serif text-xs font-bold text-white tracking-widest">
            📍 {currentMedia.city} ({currentMedia.pinyin})
          </span>
          <span className="text-[11px] text-white/70 font-light hidden md:inline border-l border-white/20 pl-2.5">
            {currentMedia.epithet}
          </span>
        </div>

        <Link to="/" className="hidden md:block text-xs font-serif tracking-widest text-white/90 hover:text-white transition-colors font-bold drop-shadow">
          返回首页 →
        </Link>
      </header>

      {/* 居中高定极简登录卡片（摒弃复杂假路书/假条形码，回归纯粹极简奢华感） */}
      <main className="relative z-10 flex flex-1 items-center justify-center p-4">
        <Card3D maxTilt={2.5} scale={1.005} className="w-full max-w-md">
          <div className="relative w-full rounded-[2.5rem] border border-[#e2dcd4] bg-[#faf8f5]/95 p-8 text-[#2c241c] shadow-2xl shadow-black/50 backdrop-blur-2xl md:p-10">
            
            {/* 纸质质感噪点 */}
            <div
              className="pointer-events-none absolute inset-0 rounded-[2.5rem] opacity-[0.06] mix-blend-multiply"
              style={{
                backgroundImage: PAPER_NOISE_SVG,
                backgroundRepeat: 'repeat',
                backgroundSize: '200px 200px',
              }}
            />

            {/* 标题区域：精准表达品牌与旅游产品定位 */}
            <div className="relative z-10 mb-8 text-center">
              <div className="inline-flex items-center space-x-1.5 rounded-full bg-[#efeae1] px-3 py-1 text-[10px] font-bold text-[#7a6e60] mb-3">
                <span>🗺️ 旅游行程路线</span>
              </div>

              <h1 className="font-serif text-3xl font-normal tracking-tight text-[#2c241c] md:text-4xl">
                {mode === "login" ? "登录云途账号" : "注册开启新行程"}
              </h1>
              <p className="mt-2.5 text-xs font-light text-[#7a6e60]">
                {mode === "login"
                  ? "跟着候鸟的航向，随时查看与生成你的专属旅游行程"
                  : "凭公测邀请码注册，即刻智能规划你的全球路线"}
              </p>
            </div>

            {/* Linux.do 快捷登录按钮与辅助说明 */}
            <div className="relative z-10 mb-6">
              <button
                type="button"
                onClick={handleLinuxDoLogin}
                disabled={linuxDoLoading}
                className="flex w-full items-center justify-center gap-2 rounded-xl border border-[#2c241c]/20 bg-[#2c241c] px-4 py-3 text-xs font-serif font-bold text-[#f5efdf] shadow-md transition-all hover:bg-black focus:outline-none focus:ring-2 focus:ring-[#2c241c] focus:ring-offset-2 focus:ring-offset-[#faf8f5] active:scale-[0.98] disabled:opacity-60"
              >
                {linuxDoLoading ? (
                  <>
                    <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-[#f5efdf] border-t-transparent" />
                    <span>正在跳转 Linux.do…</span>
                  </>
                ) : (
                  <>
                    <span className="text-sm">🐧</span>
                    <span>使用 Linux.do 登录</span>
                  </>
                )}
              </button>
              <p className="mt-2 text-center text-[11px] font-light text-[#7a6e60]">
                新用户首次接入需达到 Linux.do 1级；已接入账户不重复校验等级。
              </p>
              <div className="relative my-5 flex items-center justify-center">
                <div className="absolute inset-0 flex items-center">
                  <div className="w-full border-t border-[#e0d9cd]" />
                </div>
                <span className="relative bg-[#faf8f5] px-3 text-[11px] text-[#8c7a6b]">
                  或使用邮箱
                </span>
              </div>
            </div>

            {/* Segment Mode Tabs */}
            <div className="relative z-10 mb-7 flex rounded-2xl bg-[#efeae1] p-1 shadow-inner">
              <button
                type="button"
                onClick={() => handleTabSwitch("login")}
                className={`flex-1 rounded-xl py-2.5 text-xs font-bold transition-all duration-300 ${
                  mode === "login"
                    ? "bg-[#faf8f5] text-[#2c241c] shadow-md scale-[1.02]"
                    : "text-[#9c8e7e] hover:text-[#2c241c]"
                }`}
              >
                邮箱登录
              </button>
              <button
                type="button"
                onClick={() => handleTabSwitch("register")}
                className={`flex-1 rounded-xl py-2.5 text-xs font-bold transition-all duration-300 ${
                  mode === "register"
                    ? "bg-[#faf8f5] text-[#2c241c] shadow-md scale-[1.02]"
                    : "text-[#9c8e7e] hover:text-[#2c241c]"
                }`}
              >
                邀请码注册
              </button>
            </div>

            {infoNotice && (
              <div className="relative z-10 mb-6 rounded-xl border border-[#dcd3c5] bg-[#f0e9dc] px-4 py-3 text-xs text-[#5c5043]">
                {infoNotice}
              </div>
            )}

            <form onSubmit={handleSubmit} className="relative z-10 space-y-5" noValidate>
              {mode === "register" && (
                <div>
                  <label className="mb-1.5 block text-[10px] font-serif tracking-widest text-[#8c7a6b]" htmlFor="inv-code">
                    INVITATION CODE / 邀请码
                  </label>
                  <input
                    id="inv-code"
                    ref={invitationInputRef}
                    type="text"
                    value={invitationCode}
                    onChange={(e) => handleInvitationCodeChange(e.target.value)}
                    placeholder="输入公测邀请码"
                    className={`h-12 w-full rounded-xl border border-[#e0d9cd] bg-[#f0ebe1] px-4 font-mono text-sm tracking-wider text-[#2c241c] shadow-inner transition-all placeholder:text-[#b0a394] focus:bg-white focus:border-[#2c241c] focus:outline-none ${
                      invitationError ? "border-red-400" : ""
                    }`}
                  />
                  {invitationError && <p className="mt-1 text-xs text-red-500">{invitationError}</p>}
                </div>
              )}

              <div>
                <label className="mb-1.5 block text-[10px] font-serif tracking-widest text-[#8c7a6b]" htmlFor="user-email">
                  EMAIL ADDRESS / 电子邮箱
                </label>
                <input
                  id="user-email"
                  type="email"
                  value={email}
                  onChange={(e) => handleEmailChange(e.target.value)}
                  placeholder="name@example.com"
                  className={`h-12 w-full rounded-xl border border-[#e0d9cd] bg-[#f0ebe1] px-4 text-sm text-[#2c241c] shadow-inner transition-all placeholder:text-[#b0a394] focus:bg-white focus:border-[#2c241c] focus:outline-none ${
                    emailError ? "border-red-400" : ""
                  }`}
                />
                {emailError && <p className="mt-1 text-xs text-red-500">{emailError}</p>}
              </div>

              <div>
                <label className="mb-1.5 block text-[10px] font-serif tracking-widest text-[#8c7a6b]" htmlFor="otp-code">
                  VERIFICATION CODE / 验证码
                </label>
                <div className="flex gap-3">
                  <input
                    id="otp-code"
                    ref={otpInputRef}
                    type="text"
                    maxLength={6}
                    value={currentCode}
                    onChange={(e) => handleCodeChange(e.target.value)}
                    placeholder="6位数字"
                    className={`h-12 flex-1 rounded-xl border border-[#e0d9cd] bg-[#f0ebe1] px-4 font-mono text-sm tracking-widest text-[#2c241c] shadow-inner transition-all placeholder:text-[#b0a394] focus:bg-[#faf8f5] focus:border-[#2c241c] focus:outline-none ${
                      otpError ? "border-red-400" : ""
                    }`}
                  />
                  <button
                    type="button"
                    onClick={handleSendCode}
                    disabled={sending || countdown > 0}
                    className="min-w-[110px] rounded-xl border border-[#3c3228]/20 bg-[#3c3228]/10 px-4 text-xs font-serif font-bold text-[#3c3228] transition-all hover:bg-[#3c3228]/20 active:scale-95 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {sending ? (
                      <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-[#3c3228] border-t-transparent" />
                    ) : countdown > 0 ? (
                      `${countdown}s`
                    ) : (
                      "发送验证码"
                    )}
                  </button>
                </div>
                {otpError && <p className="mt-1 text-xs text-red-500">{otpError}</p>}
              </div>

              <div className="pt-4">
                <button
                  type="submit"
                  disabled={verifying}
                  className="flex h-13 w-full items-center justify-center rounded-xl bg-[#2c241c] py-3.5 text-xs font-serif tracking-[0.25em] text-[#f5efdf] shadow-xl transition-all duration-300 hover:bg-black hover:scale-[1.01] active:scale-95 disabled:opacity-60 uppercase font-bold"
                >
                  {verifying ? (
                    <span className="mr-2 inline-block h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
                  ) : mode === "login" ? (
                    "登录进入云途 (LOG IN)"
                  ) : (
                    "注册云途账号 (REGISTER)"
                  )}
                </button>
              </div>
            </form>
          </div>
        </Card3D>
      </main>
    </div>
  );
}
