/**
 * 等待页：左进度 + 右「城市明信片散开 → 合拢 → 登机牌扫光」
 * 全站统一通栏顶栏 + 状态级联恢复 + 自愈弱网警报 + 拍立得拟物升级
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams, Link } from 'react-router-dom';

import gsap from 'gsap';
import { ProgressTimeline } from '@/components/planning/ProgressTimeline';
import { BoardingPass } from '@/components/planning/BoardingPass';
import {
  RotatingBackground,
  useRotatingBackground,
  getCityPhotoUrls,
} from '@/components/input/RotatingBackground';
import { useTripStore } from '@/stores/tripStore';

import { useTripTaskStore } from '@/stores/tripTaskStore';
import { pollJobStatus, submitTrip, fetchResult, ApiRequestError } from '@/services/api';
import { savePendingSubmission, clearPendingSubmission } from '@/utils/pendingSubmission';
import { useJobProgress } from '@/hooks/useJobProgress';
import { webErrorMessage } from '@/constants/errors';
import { STAGE_MAP } from '@/constants/stages';
import { DEFAULT_FORM } from '@/types/form';
import type { StageCode, JobResponse } from '@/types/trip';

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

function stageIndexOf(code: StageCode | null): number {
  if (!code) return 0;
  const i = STAGES.indexOf(code);
  return i < 0 ? 0 : i;
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
            {/* 照片视口 */}
            <div className="relative h-[calc(100%-28px)] w-full overflow-hidden rounded-xl bg-gray-100">
              <img src={src} alt="" className="h-full w-full object-cover" />
              <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-black/30 via-transparent to-transparent" />
              <span className="absolute top-2 right-2 rounded-full bg-black/40 px-2 py-0.5 text-[8px] font-mono font-semibold text-white/90 backdrop-blur-xs">
                0{idx + 1}/04
              </span>
            </div>

            {/* 底部拍立得黄金下沉区 */}
            <div className="mt-2 flex items-center justify-between px-1">
              <div className="flex flex-col">
                <span className="font-mono text-[10px] font-black tracking-widest text-gray-800 uppercase leading-none">
                  {city} · {iata}
                </span>
                <span className="font-mono text-[7px] text-gray-400 mt-0.5 leading-none">
                  {coord}
                </span>
              </div>
              {/* 仿复古航空邮戳 */}
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

export default function PlanningPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const navigate = useNavigate();
  const setJob = useTripStore((s) => s.setJob);
  const setResult = useTripStore((s) => s.setResult);
  const clearResult = useTripStore((s) => s.clearResult);
  const formData = useTripStore((s) => s.formData);

  // 级联恢复目的地，防止新标签页或刷新导致表单丢失回退为生硬的“目的地”
  const taskDestination = useTripTaskStore((s) => s.getTask(jobId ?? ''))?.destination;
  const destination = formData?.to_city || taskDestination || '当前目的地';

  const stageQuotes: Record<StageCode, string[]> = useMemo(
    () => ({
      ANALYZING: [
        `正在读懂你的偏好与节奏…`,
        `正在对齐 ${destination} 的行程边界…`,
        `正在为你翻阅 ${destination} 的当地指南…`,
      ],
      PLANNING: [
        `正在筛选 ${destination} 高口碑地点…`,
        `正在计算景点之间的通勤成本…`,
        `正在收集 ${destination} 的风景与路线…`,
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
    [destination],
  );

  const [quoteIndex, setQuoteIndex] = useState(0);
  const [stageCode, setStageCode] = useState<StageCode | null>(null);
  const [failed, setFailed] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [timedOut, setTimedOut] = useState(false);
  const [networkUnstable, setNetworkUnstable] = useState(false);
  const [retrying, setRetrying] = useState(false);

  const [cardPhase, setCardPhase] = useState<CardPhase>('collect');
  const [showPass, setShowPass] = useState(false);
  const [isReadyToDepart, setIsReadyToDepart] = useState(false);
  const [readyResultUrl, setReadyResultUrl] = useState<string | null>(null);
  const [countdown, setCountdown] = useState(2);

  useEffect(() => {
    if (!isReadyToDepart) return;
    setCountdown(2);
    const interval = setInterval(() => {
      setCountdown((c) => Math.max(0, c - 1));
    }, 1000);
    return () => clearInterval(interval);
  }, [isReadyToDepart]);

  const stageIndex = stageIndexOf(stageCode);

  const { current: bgImage, incoming: bgIncoming } = useRotatingBackground(
    destination && destination !== '当前目的地' ? [destination] : [],
    'static',
  );

  const titleRef = useRef<HTMLHeadingElement>(null);
  const quoteRef = useRef<HTMLParagraphElement>(null);
  const timelineWrapRef = useRef<HTMLDivElement>(null);
  const rightRef = useRef<HTMLDivElement>(null);
  const passWrapRef = useRef<HTMLDivElement>(null);
  const passShineRef = useRef<HTMLDivElement>(null);
  const albumWrapRef = useRef<HTMLDivElement>(null);
  const signRef = useRef<HTMLDivElement>(null);
  const autoNavTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const introTl = useRef<gsap.core.Timeline | null>(null);
  const quoteTween = useRef<gsap.core.Timeline | null>(null);
  const stageTween = useRef<gsap.core.Timeline | null>(null);
  const morphTl = useRef<gsap.core.Timeline | null>(null);
  const shineTween = useRef<gsap.core.Timeline | null>(null);
  const morphingRef = useRef(false);

  const quotes = stageCode ? stageQuotes[stageCode] : stageQuotes.ANALYZING;

  const title = failed
    ? '这次规划没能完成'
    : timedOut
      ? '生成时间比预期长'
      : `正在规划你的 ${destination} 之旅`;

  const quoteText = failed
    ? '可以调整需求后重新规划'
    : timedOut
      ? '请稍后刷新查看，或重新规划'
      : quotes[quoteIndex % quotes.length];

  const playPassGloss = useCallback(() => {
    if (prefersReducedMotion() || !passWrapRef.current) return;
    shineTween.current?.kill();
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
    shineTween.current = tl;
  }, []);

  const runMorphToPass = useCallback(
    (reduce: boolean) => {
      if (morphingRef.current || (showPass && cardPhase === 'pass')) return;
      morphingRef.current = true;
      setCardPhase('pass');

      if (reduce) {
        setShowPass(true);
        morphingRef.current = false;
        return;
      }

      morphTl.current?.kill();
      morphTl.current = gsap.timeline({
        onComplete: () => {
          morphingRef.current = false;
        },
      });

      if (albumWrapRef.current) {
        morphTl.current.to(albumWrapRef.current, {
          scale: 0.88,
          opacity: 0.85,
          duration: 0.25,
          ease: 'power1.in',
        });
        morphTl.current.to(albumWrapRef.current, {
          scale: 0.4,
          opacity: 0,
          duration: 0.4,
          ease: 'power2.in',
        });
      }
      morphTl.current.add(() => {
        setShowPass(true);
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
      }, '-=0.15');
    },
    [showPass, cardPhase, playPassGloss],
  );

  const playIntro = useCallback(() => {
    const reduce = prefersReducedMotion();
    introTl.current?.kill();
    const leftEls = [
      titleRef.current,
      quoteRef.current,
      timelineWrapRef.current,
    ].filter(Boolean) as HTMLElement[];

    if (reduce) {
      gsap.set([...leftEls, rightRef.current, signRef.current], {
        clearProps: 'all',
        opacity: 1,
        y: 0,
        scale: 1,
      });
      return;
    }

    gsap.set(leftEls, { opacity: 0, y: 20 });
    gsap.set(rightRef.current, { opacity: 0, y: 24, scale: 0.97 });
    gsap.set(signRef.current, { opacity: 0, y: 12 });

    introTl.current = gsap.timeline({ defaults: { ease: 'power2.out' } });
    introTl.current
      .to(titleRef.current, { opacity: 1, y: 0, duration: 0.5 })
      .to(quoteRef.current, { opacity: 1, y: 0, duration: 0.4 }, '-=0.22')
      .to(timelineWrapRef.current, { opacity: 1, y: 0, duration: 0.45 }, '-=0.18')
      .to(rightRef.current, { opacity: 1, y: 0, scale: 1, duration: 0.6 }, '-=0.35')
      .to(signRef.current, { opacity: 1, y: 0, duration: 0.4 }, '-=0.2');
  }, []);

  useEffect(() => {
    playIntro();
    return () => {
      introTl.current?.kill();
      quoteTween.current?.kill();
      stageTween.current?.kill();
      morphTl.current?.kill();
      shineTween.current?.kill();
      if (autoNavTimer.current) clearTimeout(autoNavTimer.current);
    };
  }, [playIntro]);

  // 真实 stage 推进
  useEffect(() => {
    if (failed || timedOut) return;
    const idx = stageIndexOf(stageCode);

    if (idx < 2) {
      if (cardPhase !== 'collect') {
        setCardPhase('collect');
        setShowPass(false);
        morphingRef.current = false;
        if (albumWrapRef.current) {
          gsap.set(albumWrapRef.current, { clearProps: 'all', opacity: 1, scale: 1 });
        }
      }
    } else {
      if (cardPhase === 'pass' || showPass) {
        setShowPass(false);
        setCardPhase('collect');
        morphingRef.current = false;
      } else if (cardPhase !== 'collect') {
        setCardPhase('collect');
      }
    }

    if (prefersReducedMotion() || !timelineWrapRef.current) return;
    stageTween.current?.kill();
    stageTween.current = gsap.timeline();
    const dots = timelineWrapRef.current.querySelectorAll('li > span.absolute');
    if (dots.length) {
      stageTween.current.fromTo(
        dots,
        { scale: 0.88 },
        { scale: 1, duration: 0.4, stagger: 0.05, ease: 'back.out(1.7)' },
      );
    }
  }, [stageCode, failed, timedOut, cardPhase, showPass]);

  // 文案轮播
  useEffect(() => {
    if (failed || timedOut) return;
    const id = window.setInterval(() => {
      setQuoteIndex((i) => (i + 1) % Math.max(1, quotes.length));
    }, 5500);
    return () => clearInterval(id);
  }, [quotes.length, failed, timedOut, stageCode]);

  useEffect(() => {
    if (!quoteRef.current || prefersReducedMotion()) return;
    quoteTween.current?.kill();
    quoteTween.current = gsap.timeline();
    quoteTween.current.fromTo(
      quoteRef.current,
      { opacity: 0, y: 8 },
      { opacity: 1, y: 0, duration: 0.4, ease: 'power2.out' },
    );
  }, [quoteIndex, title, failed, timedOut, stageCode]);

  useEffect(() => {
    if (!failed || !timelineWrapRef.current || prefersReducedMotion()) return;
    gsap.fromTo(
      timelineWrapRef.current,
      { x: 0 },
      { duration: 0.45, keyframes: { x: [-6, 6, -4, 4, 0] }, ease: 'power1.inOut' },
    );
  }, [failed]);

  const [unknownState, setUnknownState] = useState(false);

  const onData = useCallback(
    (data: JobResponse): boolean => {
      // 成功接收数据，自愈清除网络不稳定警告
      setNetworkUnstable(false);

      if (data.stage_progress) {
        setStageCode(data.stage_progress.code);
        setJob(jobId!, data.status, data.stage_progress);
      }

      if (data.status === 'COMPLETED' && data.result_record_id) {
        const recordId = data.result_record_id;
        const reduce = prefersReducedMotion();
        const prefetch = fetchResult(recordId, jobId!)
          .then((res) => { setResult(recordId, jobId!, res); return res; })
          .catch(() => null);

        const go = async () => {
          const res = await prefetch;
          const target =
            res && res.plans.length === 1
              ? `/plan/${recordId}/${res.plans[0].plan_id}?job_id=${jobId}`
              : `/result/${recordId}?job_id=${jobId}`;
          navigate(target, { replace: true });
        };

        prefetch.then((res) => {
          const target =
            res && res.plans.length === 1
              ? `/plan/${recordId}/${res.plans[0].plan_id}?job_id=${jobId}`
              : `/result/${recordId}?job_id=${jobId}`;
          setReadyResultUrl(target);
        });

        // 触觉反馈
        if (typeof navigator !== 'undefined' && 'vibrate' in navigator) {
          try {
            navigator.vibrate([25, 45, 25]);
          } catch {
            // 忽略非用户交互触发或不支持设备引发的异常
          }
        }

        // 完成瞬间：合拢 → 登机牌出票扫光 → 留出 2.6s 优雅驻留时间，再平滑跳转
        if (!showPass && !morphingRef.current) {
          setCardPhase('gather');
          window.setTimeout(() => {
            runMorphToPass(reduce);
            setIsReadyToDepart(true);
            autoNavTimer.current = window.setTimeout(go, reduce ? 300 : 2600);
          }, reduce ? 0 : 380);
        } else if (showPass) {
          playPassGloss();
          setIsReadyToDepart(true);
          autoNavTimer.current = window.setTimeout(go, reduce ? 200 : 1800);
        } else {
          autoNavTimer.current = window.setTimeout(go, reduce ? 300 : 2600);
        }
        return true;
      }

      if (data.status === 'FAILED') {
        if (data.error?.code === 'GENERATION_STATUS_TIMEOUT') {
          setUnknownState(true);
          setErrorMessage('暂时无法确认任务状态，任务可能仍在继续。');
          return false;
        }

        setFailed(true);
        setErrorMessage(webErrorMessage(data.error?.code, data.error?.message));
        return true;
      }

      return false;
    },
    [jobId, navigate, setJob, setResult, showPass, runMorphToPass, playPassGloss],
  );

  const onTimeout = useCallback(() => {
    setUnknownState(true);
    setErrorMessage('暂时无法确认任务状态，任务可能仍在继续。');
  }, []);

  const onConsecutiveErrors = useCallback((count: number) => {
    setNetworkUnstable(count >= 3);
  }, []);

  const { stop } = useJobProgress({
    jobId,
    onData,
    onTimeout,
    onConsecutiveErrors,
    consecutiveErrorThreshold: 3,
    enabled: !!jobId && !failed && !timedOut && !unknownState,
  });

  const stopRef = useRef(stop);
  stopRef.current = stop;

  useEffect(() => () => {
    stopRef.current();
  }, []);

  function handleRetry() {
    setFailed(false);
    setTimedOut(false);
    setUnknownState(false);
    setErrorMessage(null);
    navigate('/');
  }

  async function handleRecheck() {
    if (!jobId) return;
    setRetrying(true);
    setErrorMessage(null);
    try {
      const data = await pollJobStatus(jobId);
      if (data.status === 'COMPLETED' && data.result_record_id) {
        setUnknownState(false);
        navigate(`/result/${data.result_record_id}?job_id=${jobId}`, { replace: true });
        return;
      }
      if (data.status === 'FAILED' && data.error?.code !== 'GENERATION_STATUS_TIMEOUT') {
        setUnknownState(false);
        setFailed(true);
        setErrorMessage(webErrorMessage(data.error?.code, data.error?.message));
        return;
      }
      setUnknownState(true);
      setErrorMessage('暂时无法确认任务状态，任务可能仍在继续。');
    } catch {
      setErrorMessage('网络查询失败，请检查网络设置后重试');
    } finally {
      setRetrying(false);
    }
  }

  async function handleRetrySame() {
    if (retrying) return;
    const retryPayload = formData || {
      ...DEFAULT_FORM,
      to_city: destination !== '当前目的地' ? destination : '',
    };
    setRetrying(true);
    setErrorMessage(null);
    clearResult();
    const pending = savePendingSubmission(retryPayload);
    try {
      const res = await submitTrip(retryPayload, pending.request_id);
      useTripTaskStore.getState().addOrUpdateTask({
        jobId: res.job_id,
        requestId: pending.request_id,
        destination: retryPayload.to_city || "目的地",
        startedAt: Date.now(),
        status: "pending",
        notificationState: "none",
      });
      clearPendingSubmission();
      setFailed(false);
      setTimedOut(false);
      setUnknownState(false);
      setStageCode(null);
      setCardPhase('collect');
      setShowPass(false);
      morphingRef.current = false;
      if (albumWrapRef.current) {
        gsap.set(albumWrapRef.current, { clearProps: 'all', opacity: 1, scale: 1 });
      }
      navigate(`/planning/${res.job_id}`, { replace: true });
    } catch (err) {
      if (err instanceof ApiRequestError) {
        if (err.status === 409 && err.code === 'ACTIVE_TRIP_EXISTS') {
          setErrorMessage(err.message);
        } else if (
          err.status === 400 ||
          err.status === 422 ||
          err.status === 429 ||
          ['REQUEST_ID_CONFLICT', 'CITY_NOT_SUPPORTED', 'VALIDATION_ERROR', 'QUOTA_EXHAUSTED'].includes(err.code)
        ) {
          clearPendingSubmission();
        }
      }
      const msg = err instanceof ApiRequestError ? err.message : '重试失败，请稍后再试';
      setErrorMessage(msg);
    } finally {
      setRetrying(false);
    }
  }

  return (
    <div className="relative min-h-screen bg-sand-50/30 selection:bg-primary-500 selection:text-white">
      {/* 壁纸背景：通透高饱和 */}
      <RotatingBackground current={bgImage} incoming={bgIncoming} />

      {/* 顶栏：全站统一全宽两端通栏 Header */}
      <header className="fixed left-0 right-0 top-0 z-30 flex w-full items-center justify-between px-5 py-3.5 sm:px-10 lg:px-14 border-b border-sand-200/80 bg-white/85 backdrop-blur-md shadow-2xs">
        <div className="flex items-center space-x-6">
          <Link to="/" className="flex items-center space-x-2">
            <img src="/logo.svg" alt="云途 YunTu" className="h-8 w-8" />
            <span className="text-xl font-black tracking-tight text-gray-900">
              云途 <span className="font-light text-emerald-600 text-sm">YunTu</span>
            </span>
          </Link>

          <nav className="hidden sm:flex items-center space-x-2 text-xs font-semibold">
            <Link
              to="/"
              className="inline-flex items-center gap-1.5 text-gray-600 hover:text-gray-900 px-3 py-1.5 rounded-lg hover:bg-sand-100 transition-colors"
            >
              <i className="fa-solid fa-compass text-gray-400 text-[11px]" />
              <span>行程规划</span>
            </Link>
          </nav>
        </div>
      </header>

      {/* 主界面网格 */}
      <main className="relative z-10 mx-auto grid min-h-screen max-w-6xl grid-cols-1 items-center gap-8 px-5 pb-12 pt-24 sm:px-8 sm:pt-28 lg:grid-cols-2 lg:gap-14 lg:pt-20">
        {/* 左侧：步骤与状态指示（定向柔光护盾确保极端高光壁纸下 WCAG 对比度安全） */}
        <section className="order-1 relative flex flex-col justify-center rounded-3xl p-4 sm:p-6 lg:p-8 -m-4 sm:-m-6 lg:-m-8 bg-gradient-to-r from-white/75 via-white/35 to-transparent backdrop-blur-[2px]">
          {/* 阶段标签与标题 */}
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
            {/* 固定高度轮播语录，杜绝上下抖动 */}
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
            aria-atomic="true"
          >
            <ProgressTimeline currentCode={stageCode} failed={failed} />
          </div>

          {/* 错误提示 */}
          {errorMessage && (
            <div className="mt-4 rounded-xl border border-red-200 bg-red-50/90 p-4 text-xs font-medium text-red-700 shadow-xs backdrop-blur-xs">
              <p className="flex items-center gap-2">
                <i className="fa-solid fa-circle-exclamation text-red-500" aria-hidden="true" />
                {errorMessage}
              </p>
            </div>
          )}

          {/* 失败自动退额确定性胶囊 */}
          {failed && (
            <div className="mt-3 inline-flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-3.5 py-1.5 text-xs font-semibold text-emerald-700 shadow-2xs">
              <i className="fas fa-check-circle text-emerald-600" aria-hidden="true" />
              本次失败未扣除额度（已自动退还）
            </div>
          )}

          {/* 弱网自愈提示 */}
          {networkUnstable && !failed && !unknownState && (
            <div className="mt-4 flex items-center gap-2 rounded-xl border border-amber-200 bg-amber-50/90 px-4 py-3 text-xs font-semibold text-amber-700 shadow-xs backdrop-blur-xs">
              <i className="fas fa-wifi text-amber-500 animate-pulse" aria-hidden="true" />
              网络连接微弱，正在持续自动同步状态…
            </div>
          )}

          {/* 交互重试区 */}
          {(failed || unknownState || timedOut) && (
            <div className="mt-6 flex flex-wrap gap-3">
              {failed && (
                <>
                  <button
                    type="button"
                    onClick={handleRetrySame}
                    disabled={retrying}
                    className="min-h-[44px] rounded-xl bg-accent-500 px-6 py-3 text-xs font-bold text-white shadow-sm transition-all hover:bg-accent-600 hover:shadow disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-300"
                  >
                    {retrying ? '正在重试...' : '再试一次'}
                  </button>
                  <button
                    type="button"
                    onClick={handleRetry}
                    className="min-h-[44px] rounded-xl border border-gray-200 bg-white px-6 py-3 text-xs font-bold text-gray-700 transition-colors hover:bg-gray-50"
                  >
                    重新规划
                  </button>
                </>
              )}
              {(unknownState || timedOut) && (
                <>
                  <button
                    type="button"
                    onClick={handleRecheck}
                    disabled={retrying}
                    className="min-h-[44px] rounded-xl bg-accent-500 px-6 py-3 text-xs font-bold text-white shadow-sm transition-all hover:bg-accent-600 disabled:opacity-60"
                  >
                    {retrying ? '正在查询...' : '重新查询状态'}
                  </button>
                  <button
                    type="button"
                    onClick={handleRetry}
                    className="min-h-[44px] rounded-xl border border-gray-200 bg-white px-6 py-3 text-xs font-bold text-gray-700 transition-colors hover:bg-gray-50"
                  >
                    返回首页
                  </button>
                </>
              )}
            </div>
          )}

          {/* 释压型后台托管微注脚（与时间轴浑然一体） */}
          {!failed && !unknownState && !timedOut && (
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
                city={destination}
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
                <BoardingPass city={destination} formData={formData} jobId={jobId} />

                {/* 双层高光扫光 */}
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

              {/* 登机牌完成态主动启程按钮（iOS HIG 44px 触控与触觉反馈） */}
              {isReadyToDepart && (
                <div className="flex flex-col items-center gap-1.5 animate-fade-in mt-5">
                  <button
                    type="button"
                    onClick={() => readyResultUrl && navigate(readyResultUrl, { replace: true })}
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
                  <span className="text-[10px] font-medium text-gray-500">
                    即将自动跳转 · 点击可立即进入
                  </span>
                </div>
              )}
            </div>
          </div>

          {/* 东方人文意境签名 + 朱红小方印 */}
          <div ref={signRef} className="mt-6 flex items-center justify-center gap-2 opacity-85 select-none sm:mt-8">
            <span className="font-serif text-sm tracking-[0.22em] text-gray-700 font-light">
              {failed ? '下次旅程 · 必定顺利' : '好行程 · 值得稍候片刻'}
            </span>
            <span className="inline-flex h-4 w-4 items-center justify-center rounded-xs bg-red-600 text-[9px] font-black text-white shadow-xs font-serif leading-none">
              途
            </span>
          </div>
        </section>
      </main>
    </div>
  );
}
