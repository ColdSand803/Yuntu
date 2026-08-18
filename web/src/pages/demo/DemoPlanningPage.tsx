/**
 * 演示页：攻略生成等待页（PlanningPage Demo）
 * 支持自由选择城市、模拟阶段推进（1~4）、合拢出票、模拟失败/弱网、以及全流程自动播放
 */
import { useEffect, useMemo, useRef, useState, useCallback } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import gsap from 'gsap';
import { DemoSwitcher } from '@/components/demo/DemoSwitcher';

import { ProgressTimeline } from '@/components/planning/ProgressTimeline';
import { BoardingPass } from '@/components/planning/BoardingPass';
import {
  RotatingBackground,
  useRotatingBackground,
  getCityPhotoUrls,
} from '@/components/input/RotatingBackground';
import { STAGE_MAP } from '@/constants/stages';
import type { StageCode } from '@/types/trip';

const STAGES: StageCode[] = ['ANALYZING', 'PLANNING', 'COMPOSING', 'FINALIZING'];

const FAN_OUT = [
  { x: -118, y: 28, rotate: -18, scale: 1 },
  { x: -42, y: -18, rotate: -6, scale: 1.02 },
  { x: 42, y: -14, rotate: 7, scale: 1.02 },
  { x: 118, y: 32, rotate: 16, scale: 1 },
];

const GATHER = [
  { x: -10, y: 4, rotate: -4, scale: 0.92 },
  { x: -3, y: -2, rotate: -1, scale: 0.94 },
  { x: 3, y: -2, rotate: 1, scale: 0.94 },
  { x: 10, y: 4, rotate: 4, scale: 0.92 },
];

const CITY_COORDS: Record<string, string> = {
  北京: "39°54'N 116°23'E",
  上海: "31°13'N 121°28'E",
  重庆: "29°33'N 106°33'E",
  成都: "30°39'N 104°04'E",
  杭州: "30°16'N 120°09'E",
  西安: "34°16'N 108°54'E",
  南京: "32°03'N 118°46'E",
  长沙: "28°12'N 112°58'E",
  青岛: "36°04'N 120°23'E",
  桂林: "25°16'N 110°17'E",
  广州: "23°08'N 113°16'E",
  武汉: "30°35'N 114°17'E",
  苏州: "31°18'N 120°37'E",
  厦门: "24°28'N 118°05'E",
  昆明: "25°02'N 102°42'E",
  三亚: "18°15'N 109°30'E",
};

const CITY_IATA: Record<string, string> = {
  北京: "PEK",
  上海: "SHA",
  重庆: "CKG",
  成都: "CTU",
  杭州: "HGH",
  西安: "XIY",
  南京: "NKG",
  长沙: "CSX",
  青岛: "TAO",
  桂林: "KWL",
  广州: "CAN",
  武汉: "WUH",
  苏州: "SZV",
  厦门: "XMN",
  昆明: "KMG",
  三亚: "SYX",
};

function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined') return false;
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

type CardPhase = 'collect' | 'gather' | 'pass';

function PostcardStage({
  city,
  stageIndex,
  phase,
  failed,
}: {
  city: string;
  stageIndex: number;
  phase: CardPhase;
  failed: boolean;
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const photos = useMemo(() => getCityPhotoUrls(city, 4), [city]);
  const lastPhase = useRef<string>('');
  const coord = CITY_COORDS[city] || "30°00'N 104°00'E";
  const iata = CITY_IATA[city] || "DEST";

  useEffect(() => {
    if (!wrapRef.current) return;
    const cards = Array.from(wrapRef.current.querySelectorAll<HTMLElement>('.mag-card'));
    if (!cards.length) return;

    const reduce = prefersReducedMotion();
    const isMobile = window.innerWidth < 640;
    const fanOut = isMobile
      ? [
          { x: -68, y: 16, rotate: -14, scale: 0.96 },
          { x: -22, y: -10, rotate: -4, scale: 1 },
          { x: 22, y: -8, rotate: 5, scale: 1 },
          { x: 68, y: 18, rotate: 14, scale: 0.96 },
        ]
      : FAN_OUT;

    gsap.killTweensOf(cards);
    const visible = Math.min(Math.max(stageIndex + 1, 1), cards.length);

    if (reduce) {
      cards.forEach((card, i) => {
        if (phase === 'pass' || i >= visible) {
          gsap.set(card, { opacity: 0, x: 0, y: 0, scale: 0.5 });
        } else if (phase === 'gather') {
          gsap.set(card, { opacity: 1, ...GATHER[i] });
        } else {
          gsap.set(card, { opacity: 1, ...fanOut[i] });
        }
      });
      return;
    }

    if (phase === 'collect') {
      cards.forEach((card, i) => {
        if (i < visible) {
          const isNew = i === visible - 1;
          gsap.to(card, {
            opacity: 1,
            x: fanOut[i].x,
            y: fanOut[i].y,
            rotate: fanOut[i].rotate,
            scale: fanOut[i].scale,
            duration: isNew ? 0.85 : 0.55,
            delay: isNew ? 0.05 : 0,
            ease: isNew ? 'power3.out' : 'power2.out',
          });
        } else {
          gsap.set(card, {
            opacity: 0,
            x: 80 + i * 15,
            y: 140,
            rotate: 20,
            scale: 0.75,
          });
        }
      });
    }

    if (phase === 'gather') {
      cards.forEach((card, i) => {
        gsap.set(card, {
          opacity: 1,
          x: fanOut[i].x,
          y: fanOut[i].y,
          rotate: fanOut[i].rotate,
          scale: fanOut[i].scale,
        });
      });
      gsap
        .timeline()
        .to(cards, {
          x: (i) => GATHER[i as number].x,
          y: (i) => GATHER[i as number].y,
          rotate: (i) => GATHER[i as number].rotate,
          scale: (i) => GATHER[i as number].scale,
          duration: 0.7,
          stagger: 0.04,
          ease: 'power2.inOut',
        })
        .to(cards, {
          x: 0,
          y: 8,
          rotate: 0,
          scale: 0.72,
          duration: 0.45,
          stagger: 0.03,
          ease: 'power2.in',
        });
    }

    if (phase === 'pass' && lastPhase.current !== 'pass') {
      gsap.to(cards, {
        x: 0,
        y: 0,
        rotate: 0,
        scale: 0.35,
        opacity: 0,
        duration: 0.45,
        stagger: 0.04,
        ease: 'power2.in',
      });
    }

    if (failed && phase !== 'pass') {
      gsap.to(cards, {
        x: '+=7',
        duration: 0.07,
        yoyo: true,
        repeat: 5,
        ease: 'power1.inOut',
      });
    }

    lastPhase.current = phase;
  }, [stageIndex, phase, failed, photos.length]);

  const photoKey = photos.join('|');
  useEffect(() => {
    if (!wrapRef.current || prefersReducedMotion()) return;
    const cards = wrapRef.current.querySelectorAll<HTMLElement>('.mag-card');
    const isMobile = window.innerWidth < 640;
    const firstFan = isMobile
      ? { x: -68, y: 16, rotate: -14, scale: 0.96 }
      : FAN_OUT[0];

    gsap.set(cards, { opacity: 0, x: 70, y: 140, rotate: 18, scale: 0.78 });
    if (cards[0]) {
      gsap.to(cards[0], {
        opacity: 1,
        x: firstFan.x,
        y: firstFan.y,
        rotate: firstFan.rotate,
        scale: firstFan.scale,
        duration: 0.95,
        delay: 0.35,
        ease: 'power3.out',
      });
    }
  }, [photoKey]);

  const caption =
    phase === 'pass'
      ? '专属路书已就绪'
      : phase === 'gather'
        ? '正在装订旅行路书…'
        : failed
          ? '规划已中断'
          : `正在收集 ${city} 的沿途风景…`;

  return (
    <div
      ref={wrapRef}
      className="relative mx-auto flex h-[290px] w-full max-w-lg items-center justify-center sm:h-[330px] lg:h-[390px] select-none"
    >
      {photos.map((src, idx) => (
        <div
          key={src}
          className="mag-card group absolute h-52 w-38 sm:h-64 sm:w-46 lg:h-76 lg:w-54 hover:z-30 cursor-pointer"
        >
          <div className="mag-card-inner relative h-full w-full overflow-hidden rounded-2xl border border-white/90 bg-white/95 p-2 pb-6 shadow-[0_20px_45px_-12px_rgba(0,0,0,0.24),0_0_0_1px_rgba(0,0,0,0.04)]">
            <div className="relative h-[calc(100%-28px)] w-full overflow-hidden rounded-xl bg-gray-100">
              <img src={src} alt="" className="h-full w-full object-cover" />
              <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-black/30 via-transparent to-transparent" />
              <span className="absolute top-2 right-2 rounded-full bg-black/40 px-2 py-0.5 text-[8px] font-mono font-semibold text-white/90 backdrop-blur-xs">
                0{idx + 1}/04
              </span>
            </div>

            <div className="mt-2 flex items-center justify-between px-1">
              <div className="flex flex-col">
                <span className="font-mono text-[10px] font-black tracking-widest text-gray-800 uppercase leading-none">
                  {city} · {iata}
                </span>
                <span className="font-mono text-[7px] text-gray-400 mt-0.5 leading-none">
                  {coord}
                </span>
              </div>
              <div className="flex h-5 w-5 items-center justify-center rounded-full border border-dashed border-gray-300 text-[7px] font-mono font-bold text-gray-400 -rotate-12 select-none">
                POST
              </div>
            </div>
          </div>
        </div>
      ))}
      <p className="absolute -bottom-2 text-[11px] font-medium tracking-[0.2em] text-gray-500 sm:bottom-0">
        {caption}
      </p>
    </div>
  );
}

export default function DemoPlanningPage() {
  const navigate = useNavigate();
  const [city, setCity] = useState('成都');
  const [stageIndex, setStageIndex] = useState(0);
  const [cardPhase, setCardPhase] = useState<CardPhase>('collect');
  const [showPass, setShowPass] = useState(false);
  const [failed, setFailed] = useState(false);
  const [networkUnstable, setNetworkUnstable] = useState(false);
  const [isReadyToDepart, setIsReadyToDepart] = useState(false);
  const [autoPlay, setAutoPlay] = useState(true);
  const [countdown, setCountdown] = useState(2);

  useEffect(() => {
    if (!isReadyToDepart) return;
    setCountdown(2);
    const interval = setInterval(() => {
      setCountdown((c) => {
        if (c <= 1) {
          clearInterval(interval);
          navigate('/demo/detail-light');
          return 0;
        }
        return c - 1;
      });
    }, 1000);
    return () => clearInterval(interval);
  }, [isReadyToDepart, navigate]);

  const stageCode = failed ? null : STAGES[stageIndex];

  const stageQuotes: Record<StageCode, string[]> = useMemo(
    () => ({
      ANALYZING: [
        `正在读懂你的偏好与节奏…`,
        `正在对齐 ${city} 的行程边界…`,
        `正在为你翻阅 ${city} 的当地指南…`,
      ],
      PLANNING: [
        `正在筛选 ${city} 高口碑地点…`,
        `正在计算景点之间的通勤成本…`,
        `正在收集 ${city} 的风景与路线…`,
      ],
      COMPOSING: [
        `正在把风景收进日程…`,
        `正在把必去点嵌进可走的路线…`,
        `正在编排每日路线与用餐节奏…`,
      ],
      FINALIZING: [
        `正在校验合理性与节奏…`,
        `快好了，正在整理成可跟着走的路书…`,
        `正在做最后的检查…`,
      ],
    }),
    [city],
  );

  const [quoteIndex, setQuoteIndex] = useState(0);
  const quotes = stageCode ? stageQuotes[stageCode] : stageQuotes.ANALYZING;

  const { current: bgImage, incoming: bgIncoming } = useRotatingBackground(
    [city],
    'static',
  );

  const titleRef = useRef<HTMLHeadingElement>(null);
  const quoteRef = useRef<HTMLParagraphElement>(null);
  const timelineWrapRef = useRef<HTMLDivElement>(null);
  const passWrapRef = useRef<HTMLDivElement>(null);
  const passShineRef = useRef<HTMLDivElement>(null);
  const albumWrapRef = useRef<HTMLDivElement>(null);

  const playPassGloss = useCallback(() => {
    if (prefersReducedMotion() || !passWrapRef.current) return;
    const soft = passShineRef.current;
    const blade = passWrapRef.current.querySelector<HTMLElement>('.pass-gloss-blade');
    const tl = gsap.timeline();
    if (soft) {
      gsap.set(soft, { opacity: 1, xPercent: -130, yPercent: -15 });
      tl.to(soft, { xPercent: 130, yPercent: 15, duration: 0.58, ease: 'power2.inOut' }, 0);
      tl.set(soft, { opacity: 0, xPercent: -130 }, '>');
    }
    if (blade) {
      gsap.set(blade, { opacity: 0.95, left: '-35%', top: '-20%' });
      tl.to(blade, { left: '110%', top: '10%', duration: 0.48, ease: 'power3.inOut' }, 0.06);
      tl.set(blade, { opacity: 0, left: '-35%' }, '>');
    }
  }, []);

  const runMorphToPass = useCallback(() => {
    setShowPass(true);
    setCardPhase('pass');
    setIsReadyToDepart(true);
    requestAnimationFrame(() => {
      if (!passWrapRef.current) return;
      gsap.fromTo(
        passWrapRef.current,
        { opacity: 0, y: 40, rotate: 10, scale: 0.84 },
        {
          opacity: 1,
          y: 0,
          rotate: 0,
          scale: 1,
          duration: 0.7,
          ease: 'power3.out',
          onComplete: () => playPassGloss(),
        },
      );
    });
  }, [playPassGloss]);

  // 自动播放演示时钟
  useEffect(() => {
    if (!autoPlay || failed) return;
    const timer = setInterval(() => {
      setStageIndex((prev) => {
        if (prev < 3) {
          return prev + 1;
        } else {
          // 4 步完成，合拢并成票
          setCardPhase('gather');
          setTimeout(() => {
            runMorphToPass();
          }, 400);
          clearInterval(timer);
          return 3;
        }
      });
    }, 2800);
    return () => clearInterval(timer);
  }, [autoPlay, failed, runMorphToPass]);

  // 语录轮播
  useEffect(() => {
    const id = setInterval(() => {
      setQuoteIndex((i) => (i + 1) % Math.max(1, quotes.length));
    }, 4500);
    return () => clearInterval(id);
  }, [quotes.length]);

  const handleReset = (newCity?: string) => {
    if (newCity) setCity(newCity);
    setStageIndex(0);
    setCardPhase('collect');
    setShowPass(false);
    setIsReadyToDepart(false);
    setFailed(false);
    setNetworkUnstable(false);
    setAutoPlay(true);
    if (albumWrapRef.current) {
      gsap.set(albumWrapRef.current, { clearProps: 'all', opacity: 1, scale: 1 });
    }
  };

  const title = failed ? '这次规划没能完成' : `正在规划你的 ${city} 之旅`;
  const quoteText = failed ? '可以调整需求后重新规划' : quotes[quoteIndex % quotes.length];

  return (
    <div className="relative min-h-screen bg-sand-50/30 pb-24 selection:bg-primary-500 selection:text-white">
      <RotatingBackground current={bgImage} incoming={bgIncoming} />

      {/* 顶部控制栏 (Demo 控制台) */}
      <aside className="relative z-40 bg-gray-900/90 text-white px-5 py-2.5 backdrop-blur-md border-b border-white/10 shadow-md">
        <div className="max-w-6xl mx-auto flex flex-wrap items-center justify-between gap-3 text-xs">
          <div className="flex items-center gap-2">
            <span className="font-bold text-emerald-400 flex items-center gap-1.5">
              <i className="fa-solid fa-sliders" />
              <span>等待页交互演示台</span>
            </span>
            <span className="text-gray-400">|</span>
            <span className="text-gray-300">切换城市：</span>
            {['成都', '西安', '北京', '杭州', '重庆', '厦门'].map((c) => (
              <button
                key={c}
                type="button"
                onClick={() => handleReset(c)}
                className={`px-2.5 py-0.5 rounded-full font-semibold transition-all ${
                  city === c ? 'bg-primary-500 text-white' : 'bg-white/10 text-gray-300 hover:bg-white/20'
                }`}
              >
                {c}
              </button>
            ))}
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => {
                setAutoPlay(false);
                setStageIndex((i) => Math.min(3, i + 1));
                if (stageIndex >= 2) {
                  setCardPhase('gather');
                  setTimeout(() => runMorphToPass(), 400);
                }
              }}
              className="px-2.5 py-1 rounded-lg bg-white/10 hover:bg-white/20 text-gray-200"
            >
              下一步 ➔
            </button>
            <button
              type="button"
              onClick={() => setNetworkUnstable((u) => !u)}
              className={`px-2.5 py-1 rounded-lg ${
                networkUnstable ? 'bg-amber-600 text-white' : 'bg-white/10 text-gray-200'
              }`}
            >
              模拟弱网
            </button>
            <button
              type="button"
              onClick={() => {
                setFailed(true);
                setAutoPlay(false);
              }}
              className="px-2.5 py-1 rounded-lg bg-red-600/80 hover:bg-red-600 text-white"
            >
              模拟失败
            </button>
            <button
              type="button"
              onClick={() => handleReset()}
              className="px-3 py-1 rounded-lg bg-emerald-600 hover:bg-emerald-500 font-bold text-white shadow-xs"
            >
              <i className="fa-solid fa-rotate-right mr-1" /> 重播
            </button>
          </div>
        </div>
      </aside>

      {/* 顶栏：全站统一全宽两端通栏 Header */}
      <header className="sticky top-0 z-30 flex w-full items-center justify-between px-5 py-3.5 sm:px-10 lg:px-14 border-b border-sand-200/80 bg-white/85 backdrop-blur-md shadow-2xs">
        <div className="flex items-center space-x-6">
          <Link to="/" className="flex items-center space-x-2">
            <img src="/logo.svg" alt="云途 YunTu" className="h-8 w-8" />
            <span className="text-xl font-black tracking-tight text-gray-900">
              云途 <span className="font-light text-emerald-600 text-sm">YunTu</span>
            </span>
          </Link>

          <nav className="hidden sm:flex items-center space-x-2 text-xs font-semibold">
            <Link
              to="/demo/input-capsule"
              className="inline-flex items-center gap-1.5 text-gray-600 hover:text-gray-900 px-3 py-1.5 rounded-lg hover:bg-sand-100 transition-colors"
            >
              <i className="fa-solid fa-compass text-gray-400 text-[11px]" />
              <span>行程规划</span>
            </Link>
          </nav>
        </div>
      </header>

      {/* 主界面网格 */}
      <main className="relative z-10 mx-auto grid min-h-[calc(100vh-140px)] max-w-6xl grid-cols-1 items-center gap-8 px-5 pb-12 pt-8 sm:px-8 lg:grid-cols-2 lg:gap-14">
        {/* 左侧：步骤与状态指示（定向柔光护盾确保极端高光壁纸下 WCAG 对比度安全） */}
        <section className="order-1 relative flex flex-col justify-center rounded-3xl p-4 sm:p-6 lg:p-8 -m-4 sm:-m-6 lg:-m-8 bg-gradient-to-r from-white/75 via-white/35 to-transparent backdrop-blur-[2px]">
          <div className="mb-4">
            <div className="inline-flex items-center gap-2 rounded-full border border-emerald-200/80 bg-emerald-50/80 px-3 py-1 text-xs font-bold text-emerald-800 shadow-2xs backdrop-blur-md">
              <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
              <span>
                {stageCode
                  ? `阶段 0${stageIndex + 1}/04 · ${STAGE_MAP[stageCode].label}`
                  : '正在初始化任务'}
              </span>
            </div>
            <h1
              ref={titleRef}
              className="mt-3 text-2xl font-black text-gray-900 tracking-tight sm:text-3xl xl:text-4xl"
            >
              {title}
            </h1>
            <div className="mt-2 h-6 overflow-hidden">
              <p ref={quoteRef} className="text-xs sm:text-sm font-medium text-gray-600 truncate">
                {quoteText}
              </p>
            </div>
          </div>

          {/* 时间轴容器：开放式通透设计 */}
          <div
            ref={timelineWrapRef}
            className="py-2"
            aria-live="polite"
          >
            <ProgressTimeline currentCode={stageCode} failed={failed} />
          </div>

          {failed && (
            <div className="mt-3 inline-flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-3.5 py-1.5 text-xs font-semibold text-emerald-700 shadow-2xs">
              <i className="fas fa-check-circle text-emerald-600" aria-hidden="true" />
              本次失败未扣除额度（已自动退还）
            </div>
          )}

          {networkUnstable && !failed && (
            <div className="mt-4 flex items-center gap-2 rounded-xl border border-amber-200 bg-amber-50/90 px-4 py-3 text-xs font-semibold text-amber-700 shadow-xs backdrop-blur-xs">
              <i className="fas fa-wifi text-amber-500 animate-pulse" aria-hidden="true" />
              网络连接微弱，正在持续自动同步状态…
            </div>
          )}

          {/* 释压型后台托管微注脚（与时间轴浑然一体） */}
          {!failed && (
            <div className="mt-6 pt-5 border-t border-gray-900/10 flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-xs text-gray-500">
              <div className="flex items-center gap-1.5 font-medium">
                <i className="fa-solid fa-cloud-check text-emerald-600 shrink-0" aria-hidden="true" />
                <span>已开启后台托管 · 可随时离开，完成后将自动在「我的行程」保留</span>
              </div>
              <span className="font-mono text-[11px] text-gray-400 font-semibold shrink-0">
                预计 30-45s
              </span>
            </div>
          )}
        </section>

        {/* 右侧：拍立得明信片 → 登机牌出票 */}
        <section className="order-2 flex flex-col items-center justify-center relative">
          <div
            className="ambient-glow-sphere pointer-events-none absolute -inset-8 z-0 opacity-80"
            aria-hidden="true"
          />

          <div
            ref={albumWrapRef}
            className="relative flex h-[380px] w-full max-w-[420px] items-center justify-center sm:h-[440px]"
          >
            {/* 拍立得明信片舞台 */}
            <div
              className={
                cardPhase === 'gather'
                  ? 'pass-converge flex h-full w-full items-center justify-center'
                  : 'flex h-full w-full items-center justify-center'
              }
              style={{ visibility: showPass ? 'hidden' : 'visible' }}
            >
              <PostcardStage
                city={city}
                stageIndex={stageIndex}
                phase={cardPhase}
                failed={failed}
              />
            </div>

            {/* 登机牌出票容器 */}
            <div
              ref={passWrapRef}
              className="flex w-full flex-col items-center justify-center"
              style={{
                opacity: showPass ? 1 : 0,
                pointerEvents: showPass ? 'auto' : 'none',
                position: showPass ? 'relative' : 'absolute',
                inset: showPass ? undefined : 0,
              }}
            >
              <div className="relative isolate w-[340px] max-w-full overflow-hidden rounded-2xl">
                <BoardingPass
                  city={city}
                  formData={{
                    to_city: city,
                    days: 3,
                    people_count: 2,
                    start_date: '2026-08-20',
                    end_date: '2026-08-22',
                    preferences: ['美食', '人文'],
                    avoid: [],
                    notes: '',
                  }}
                  jobId="job_demo_9824"
                />

                <div
                  ref={passShineRef}
                  aria-hidden="true"
                  className="pointer-events-none absolute inset-0 z-10 opacity-0"
                  style={{
                    background:
                      'linear-gradient(115deg, transparent 0%, transparent 38%, rgba(255,255,255,0.08) 42%, rgba(255,248,230,0.55) 48%, rgba(255,255,255,0.35) 52%, rgba(255,255,255,0.06) 58%, transparent 62%, transparent 100%)',
                    mixBlendMode: 'soft-light',
                  }}
                />
                <div
                  aria-hidden="true"
                  className="pointer-events-none absolute inset-0 z-20 overflow-hidden rounded-2xl"
                >
                  <div
                    className="pass-gloss-blade absolute -inset-y-8 w-[28%] -skew-x-12 opacity-0"
                    style={{
                      background:
                        'linear-gradient(90deg, transparent, rgba(255,255,255,0.65), rgba(255,236,179,0.35), transparent)',
                      filter: 'blur(0.5px)',
                    }}
                  />
                </div>
              </div>

              {isReadyToDepart && (
                <div className="flex flex-col items-center gap-1.5 animate-fade-in mt-5">
                  <button
                    type="button"
                    onClick={() => navigate('/demo/detail-light')}
                    className="group relative inline-flex min-h-[44px] items-center gap-2.5 overflow-hidden rounded-full bg-emerald-600 px-8 py-3 text-xs font-black text-white shadow-lg shadow-emerald-600/30 transition-all hover:bg-emerald-700 hover:scale-[1.03] active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400"
                  >
                    <span className="relative z-10 flex items-center gap-2">
                      <span>路书已就绪 · 查看路书详情</span>
                      <span className="font-mono text-[11px] font-bold bg-black/20 px-2 py-0.5 rounded-full">
                        {countdown}s
                      </span>
                    </span>
                    <i className="fa-solid fa-arrow-right relative z-10 text-[10px] transition-transform group-hover:translate-x-1" aria-hidden="true" />
                  </button>
                  <span className="text-[10px] font-medium text-gray-400">
                    即将自动跳转 · 点击可立即进入
                  </span>
                </div>
              )}
            </div>
          </div>

          <div className="mt-6 flex items-center justify-center gap-2 opacity-85 select-none sm:mt-8">
            <span className="font-serif text-sm tracking-[0.22em] text-gray-700 font-light">
              {failed ? '下次旅程 · 必定顺利' : '好行程 · 值得稍候片刻'}
            </span>
            <span className="inline-flex h-4 w-4 items-center justify-center rounded-xs bg-red-600 text-[9px] font-black text-white shadow-xs font-serif leading-none">
              途
            </span>
          </div>
        </section>
      </main>

      <DemoSwitcher />
    </div>
  );
}
