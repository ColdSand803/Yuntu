import type React from "react";
import { ChevronDown } from "lucide-react";

export interface CollapsibleSectionProps {
  id?: string;
  title: React.ReactNode;
  summary?: React.ReactNode;
  expanded: boolean;
  onToggle: () => void;
  children: React.ReactNode;
  className?: string;
  headerClassName?: string;
  contentClassName?: string;
  headerRight?: React.ReactNode;
  ariaLabel?: string;
}

/**
 * 通用折叠/展开卡片容器组件
 * 支持标题、摘要预览、头部右侧徽章与平滑 CSS Grid 动画
 * 无论展开与否，外层 section id 始终保留在 DOM 中，确保 ScrollSpy 与锚点定位兼容
 */
export function CollapsibleSection({
  id,
  title,
  summary,
  expanded,
  onToggle,
  children,
  className = "",
  headerClassName = "",
  contentClassName = "",
  headerRight,
  ariaLabel,
}: CollapsibleSectionProps) {
  const contentId = id ? `${id}-content` : undefined;

  return (
    <section
      id={id}
      className={`scroll-mt-24 ${className}`}
      aria-label={typeof title === "string" ? title : ariaLabel}
    >
      <div className="relative overflow-hidden rounded-3xl bg-white shadow-card border border-sand-200/80 transition-shadow hover:shadow-card-hover">
        {/* 折叠/展开控制头部 */}
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={expanded}
          aria-controls={contentId}
          className={`w-full text-left transition-colors flex items-center justify-between gap-3 p-5 sm:p-7 group cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-300 ${
            expanded ? "border-b border-sand-200/60 pb-5 sm:pb-6" : ""
          } ${headerClassName}`}
        >
          <div className="flex flex-wrap items-center gap-2.5 sm:gap-3 min-w-0">
            {typeof title === "string" ? (
              <h2 className="text-lg sm:text-2xl font-extrabold text-gray-900 tracking-tight truncate">
                {title}
              </h2>
            ) : (
              title
            )}
            {summary && (
              <span className="text-xs sm:text-sm font-medium text-gray-500 truncate">
                {summary}
              </span>
            )}
          </div>

          <div className="flex shrink-0 items-center gap-2.5 sm:gap-3">
            {headerRight}
            <span className="inline-flex items-center gap-1.5 rounded-full bg-sand-100/90 border border-sand-200/60 px-3 py-1 text-xs font-semibold text-gray-600 transition-colors group-hover:bg-primary-50 group-hover:text-primary-700 group-hover:border-primary-200">
              <span>{expanded ? "收起" : "展开"}</span>
              <ChevronDown
                size={10}
                className={`transition-transform duration-300 ${
                  expanded ? "rotate-180 text-primary-600" : "text-gray-400"
                }`}
                aria-hidden="true"
              />
            </span>
          </div>
        </button>

        {/* 内容展开容器：CSS Grid 0fr / 1fr 平滑动画 */}
        <div
          id={contentId}
          className={`grid transition-[grid-template-rows,opacity] duration-300 ease-out ${
            expanded
              ? "grid-rows-[1fr] opacity-100"
              : "grid-rows-[0fr] opacity-0 pointer-events-none"
          }`}
        >
          <div className="overflow-hidden min-h-0">
            <div className={`p-6 sm:p-8 pt-5 sm:pt-6 ${contentClassName}`}>
              {children}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
