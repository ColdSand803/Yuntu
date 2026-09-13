import { useEffect, useRef, useState } from "react";
import type { TripPlace, PlaceDetail, PlaceGalleryImage } from "@/types/trip";
import { categoryIcon, isAnchorRole } from "@/constants/places";
import { fetchPlaceDetail } from "@/services/api";
import {
  ChevronLeft,
  ChevronRight,
  X,
  Check,
  TriangleAlert,
  Layers,
  MessageSquare,
  MapPinned,
  Navigation,
} from "lucide-react";

interface PlaceDetailModalProps {
  place: TripPlace | null;
  isMustInclude?: boolean;
  onClose: () => void;
}

function responsiveSrcSet(image: PlaceGalleryImage): string {
  const variants = [image.thumb, image.mobile, image.desktop];
  const byWidth = new Map<number, string>();
  variants.forEach((variant) => byWidth.set(variant.width, variant.url));
  return [...byWidth.entries()]
    .sort(([left], [right]) => left - right)
    .map(([width, url]) => `${url} ${width}w`)
    .join(", ");
}

export function PlaceDetailModal({
  place,
  isMustInclude,
  onClose,
}: PlaceDetailModalProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const touchStartXRef = useRef<number | null>(null);
  const galleryCountRef = useRef(0);

  // POI 详情（v0.8.5）：打开时按 place_id 请求；失败局部降级，仍显示基础信息
  const [detail, setDetail] = useState<PlaceDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [activeImage, setActiveImage] = useState(0);
  const [failedAssets, setFailedAssets] = useState<Set<string>>(
    () => new Set(),
  );

  useEffect(() => {
    if (!place) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    setDetail(null);
    setLoading(true);
    setActiveImage(0);
    setFailedAssets(new Set());
    fetchPlaceDetail(place.place_id)
      .then((d) => {
        if (!cancelled) setDetail(d);
      })
      .catch(() => undefined)
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [place]);

  useEffect(() => {
    if (!place) return;
    previousFocusRef.current = document.activeElement as HTMLElement | null;
    requestAnimationFrame(() => panelRef.current?.focus());

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
        return;
      }
      if (e.key === "ArrowRight" && galleryCountRef.current > 1) {
        e.preventDefault();
        setActiveImage((current) => (current + 1) % galleryCountRef.current);
        return;
      }
      if (e.key === "ArrowLeft" && galleryCountRef.current > 1) {
        e.preventDefault();
        setActiveImage(
          (current) =>
            (current - 1 + galleryCountRef.current) % galleryCountRef.current,
        );
        return;
      }

      // 焦点陷阱：Tab 键循环焦点在弹窗内
      if (e.key === "Tab") {
        const panel = panelRef.current;
        if (!panel) return;

        const focusableElements = panel.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
        );
        const focusable = Array.from(focusableElements);
        if (focusable.length === 0) return;

        const firstFocusable = focusable[0];
        const lastFocusable = focusable[focusable.length - 1];

        if (e.shiftKey) {
          // Shift+Tab: 如果在第一个元素，跳到最后一个
          if (document.activeElement === firstFocusable) {
            e.preventDefault();
            lastFocusable.focus();
          }
        } else {
          // Tab: 如果在最后一个元素，跳到第一个
          if (document.activeElement === lastFocusable) {
            e.preventDefault();
            firstFocusable.focus();
          }
        }
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      previousFocusRef.current?.focus();
    };
  }, [place, onClose]);

  if (!place) return null;

  // 优先用后端详情字段，缺失回退到 TripPlace 基础信息
  const typeLabel = detail?.place_type ?? place.category;
  // 简介只用后端真实 summary，不回退 place.brief（brief 是生成期占位脏文案，如"写成咖啡/茶歇休息点"）
  const summary = detail?.summary ?? "";
  const reasons = detail?.top_reasons ?? [];
  const warnings = detail?.warnings ?? [];
  const sourceCount = detail?.source_count ?? 0;
  const mentionCount = detail?.mention_count ?? 0;
  const showCredibility = sourceCount > 0 || mentionCount > 0;
  // 详情已加载完成、但没有任何可展示的增强字段时，提示"暂无更多详情"
  const hasExtra =
    reasons.length > 0 ||
    warnings.length > 0 ||
    showCredibility ||
    !!detail?.summary;
  const gallery = (detail?.gallery ?? []).filter(
    (image) => !failedAssets.has(image.asset_id),
  );
  galleryCountRef.current = gallery.length;
  const safeImageIndex =
    gallery.length > 0 ? Math.min(activeImage, gallery.length - 1) : 0;
  const currentImage = gallery[safeImageIndex];
  const showGallery = loading || Boolean(currentImage);

  const moveGallery = (direction: -1 | 1) => {
    if (gallery.length < 2) return;
    setActiveImage(
      (current) => (current + direction + gallery.length) % gallery.length,
    );
  };

  const handleImageFailure = (assetId: string) => {
    setFailedAssets((current) => new Set(current).add(assetId));
    setActiveImage(0);
  };

  return (
    <>
      <div
        className="animate-fade-in fixed inset-0 z-[110] bg-gray-900/60 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        className="animate-slide-up fixed inset-x-0 bottom-0 z-[110] lg:inset-0 lg:flex lg:items-center lg:justify-center"
        onClick={(e) => {
          if (e.target === e.currentTarget) onClose();
        }}
      >
        <div
          ref={panelRef}
          role="dialog"
          aria-modal="true"
          aria-label={place.name}
          tabIndex={-1}
          className="flex max-h-[85vh] w-full flex-col overflow-hidden rounded-t-[2rem] bg-white shadow-2xl outline-none lg:max-w-md lg:rounded-[2rem]"
        >
          <div
            className="flex-1 overflow-y-auto p-6 sm:p-8"
            style={{ overscrollBehavior: "contain" }}
          >
            {showGallery && (
              <section className="mb-6" aria-label={`${place.name}实拍画廊`}>
                {loading && (
                  <div
                    className="aspect-[4/3] animate-pulse overflow-hidden rounded-[1.4rem] bg-gradient-to-br from-sand-100 via-white to-sand-200"
                    aria-label="图片加载中"
                  >
                    <div className="h-full w-full animate-[pulse_1.8s_ease-in-out_infinite] bg-[linear-gradient(110deg,transparent_30%,rgba(255,255,255,.65)_48%,transparent_66%)] bg-[length:220%_100%]" />
                  </div>
                )}
                {!loading && currentImage && (
                  <div
                    className="group/gallery relative aspect-[4/3] touch-pan-y overflow-hidden rounded-[1.4rem] bg-sand-100 shadow-[0_18px_50px_-28px_rgba(57,45,31,.55)]"
                    onTouchStart={(event) => {
                      touchStartXRef.current =
                        event.changedTouches[0]?.clientX ?? null;
                    }}
                    onTouchEnd={(event) => {
                      const start = touchStartXRef.current;
                      const end = event.changedTouches[0]?.clientX;
                      touchStartXRef.current = null;
                      if (
                        start == null ||
                        end == null ||
                        Math.abs(start - end) < 40
                      )
                        return;
                      moveGallery(start > end ? 1 : -1);
                    }}
                  >
                    <img
                      key={currentImage.asset_id}
                      src={currentImage.thumb.url}
                      srcSet={responsiveSrcSet(currentImage)}
                      sizes="(min-width: 1024px) 384px, calc(100vw - 48px)"
                      width={currentImage.desktop.width}
                      height={currentImage.desktop.height}
                      alt={currentImage.alt_text}
                      loading={safeImageIndex === 0 ? "eager" : "lazy"}
                      fetchPriority={safeImageIndex === 0 ? "high" : "auto"}
                      decoding="async"
                      onError={() => handleImageFailure(currentImage.asset_id)}
                      className="h-full w-full object-cover"
                    />
                    <div className="pointer-events-none absolute inset-x-0 bottom-0 h-20 bg-gradient-to-t from-gray-950/45 to-transparent" />
                    <p className="absolute bottom-4 left-4 text-[10px] font-bold uppercase tracking-[0.2em] text-white/90">
                      实拍 · {safeImageIndex + 1}/{gallery.length}
                    </p>
                    {gallery.length > 1 && (
                      <>
                        <button
                          type="button"
                          onClick={() => moveGallery(-1)}
                          aria-label="上一张图片"
                          className="absolute left-3 top-1/2 hidden h-10 w-10 -translate-y-1/2 items-center justify-center rounded-full bg-white/90 text-gray-700 shadow-md transition hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-300 lg:flex"
                        >
                          <ChevronLeft size={16} aria-hidden="true" />
                        </button>
                        <button
                          type="button"
                          onClick={() => moveGallery(1)}
                          aria-label="下一张图片"
                          className="absolute right-3 top-1/2 hidden h-10 w-10 -translate-y-1/2 items-center justify-center rounded-full bg-white/90 text-gray-700 shadow-md transition hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-300 lg:flex"
                        >
                          <ChevronRight size={16} aria-hidden="true" />
                        </button>
                      </>
                    )}
                  </div>
                )}
                {gallery.length > 1 && (
                  <div
                    className="mt-3 flex items-center justify-center gap-2"
                    aria-label="图片位置"
                  >
                    {gallery.map((image, index) => (
                      <button
                        key={image.asset_id}
                        type="button"
                        onClick={() => setActiveImage(index)}
                        aria-label={`查看第 ${index + 1} 张图片`}
                        aria-current={
                          index === safeImageIndex ? "true" : undefined
                        }
                        className={`h-2 rounded-full transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-300 focus-visible:ring-offset-2 ${
                          index === safeImageIndex
                            ? "w-6 bg-primary-600"
                            : "w-2 bg-sand-300 hover:bg-sand-400"
                        }`}
                      />
                    ))}
                  </div>
                )}
                {gallery.length > 0 && (
                  <p className="sr-only" aria-live="polite">
                    第 {safeImageIndex + 1} 张，共 {gallery.length} 张
                  </p>
                )}
              </section>
            )}

            <div className="mb-8 flex items-start justify-between">
              <div className="flex items-center gap-4">
                <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-sand-100/50 text-2xl shadow-sm">
                  {categoryIcon(typeLabel)}
                </div>
                <div>
                  <h2 className="font-display text-2xl font-bold tracking-tight text-gray-900">
                    {place.name}
                  </h2>
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <span className="rounded-full border border-gray-200 px-2 py-0.5 text-[10px] font-bold uppercase tracking-widest text-gray-500">
                      {typeLabel}
                    </span>
                    {isMustInclude && (
                      <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[10px] font-bold text-emerald-700">
                        你的必去
                      </span>
                    )}
                    {detail?.district && (
                      <span className="text-xs font-medium text-gray-400">
                        · {detail.district}
                      </span>
                    )}
                    {isAnchorRole(place.role) && (
                      <span className="rounded-full bg-primary-50 px-2 py-0.5 text-[10px] font-bold tracking-widest text-primary-700">
                        核心景点
                      </span>
                    )}
                  </div>
                </div>
              </div>
              <button
                onClick={onClose}
                aria-label="关闭"
                className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-gray-50 text-gray-400 transition-all hover:scale-105 hover:bg-gray-200 hover:text-gray-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-300"
              >
                <X size={16} aria-hidden="true" />
              </button>
            </div>

            {/* 简介 */}
            {summary && (
              <div className="mb-4">
                <h3 className="mb-2 text-sm font-semibold text-primary-800">
                  简介
                </h3>
                <p className="text-sand-600 text-sm leading-relaxed">
                  {summary}
                </p>
              </div>
            )}

            {/* 推荐理由 */}
            {reasons.length > 0 && (
              <div className="mb-4">
                <h3 className="mb-2 text-sm font-semibold text-primary-800">
                  推荐理由
                </h3>
                <ul className="space-y-1.5">
                  {reasons.map((r) => (
                    <li
                      key={r}
                      className="text-sand-600 flex items-start gap-2 text-sm"
                    >
                      <Check
                        size={12}
                        className="mt-0.5 shrink-0 text-primary-500"
                        aria-hidden="true"
                      />
                      <span className="leading-relaxed">{r}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* 注意事项（橙色提醒条，与天气提醒统一） */}
            {warnings.length > 0 && (
              <div className="mb-4 flex items-start gap-2 rounded-lg border border-accent-100 bg-accent-50 px-3 py-2.5">
                <TriangleAlert
                  size={12}
                  className="mt-0.5 shrink-0 text-accent-500"
                  aria-hidden="true"
                />
                <div className="space-y-1">
                  {warnings.map((w) => (
                    <p
                      key={w}
                      className="text-[13px] leading-relaxed text-accent-700"
                    >
                      {w}
                    </p>
                  ))}
                </div>
              </div>
            )}

            {/* 可信度/热度 */}
            {showCredibility && (
              <div className="text-sand-600 mb-4 flex items-center gap-3 text-xs">
                {sourceCount > 0 && (
                  <span className="inline-flex items-center gap-1">
                    <Layers
                      size={16}
                      className="text-primary-400"
                      aria-hidden="true"
                    />
                    综合 {sourceCount} 个来源
                  </span>
                )}
                {mentionCount > 0 && (
                  <span className="inline-flex items-center gap-1">
                    <MessageSquare
                      size={16}
                      className="text-primary-400"
                      aria-hidden="true"
                    />
                    {mentionCount} 次提及
                  </span>
                )}
              </div>
            )}

            {/* loading / 无更多详情 */}
            {!loading && !hasExtra && (
              <div className="my-4 flex flex-col items-center justify-center gap-1 rounded-2xl bg-sand-50/80 p-5 text-center border border-sand-200/60">
                <MapPinned size={18} className="text-primary-400 mb-1" aria-hidden="true" />
                <p className="text-xs font-medium text-gray-700">
                  当前地点暂未收录深度图文百科
                </p>
                <p className="text-[11px] text-gray-400">
                  已为你规划在该日的行程节奏中，可直接点击下方按钮导航前往
                </p>
              </div>
            )}
          </div>

          {/* 底部吸顶按钮：坐标改为高德地图链接 */}
          {place.longitude != null && place.latitude != null && (
            <div className="border-t border-gray-100 bg-white p-4 sm:px-8 sm:py-5">
              <a
                href={`https://uri.amap.com/marker?position=${place.longitude},${place.latitude}&name=${encodeURIComponent(place.name)}`}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex w-full items-center justify-center gap-2 rounded-full bg-sand-100 px-5 py-3.5 text-sm font-bold text-gray-700 transition-colors hover:bg-sand-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-300"
              >
                <Navigation
                  size={16}
                  className="text-primary-600"
                  aria-hidden="true"
                />
                在高德地图中查看路线
              </a>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
