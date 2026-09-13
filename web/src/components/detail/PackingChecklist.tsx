import type { PackingChecklistGroup } from "@/types/trip";
import { Luggage, Check } from "lucide-react";

interface PackingChecklistProps {
  groups: PackingChecklistGroup[];
}

export function PackingChecklist({ groups }: PackingChecklistProps) {
  if (!groups || groups.length === 0) return null;

  const totalItems = groups.reduce((acc, g) => acc + g.items.length, 0);

  return (
    <div className="flex h-full flex-col rounded-3xl border border-sand-200/90 bg-white p-6 sm:p-7 shadow-card transition-shadow hover:shadow-card-hover">
      {/* 模块头部 */}
      <div className="mb-5 flex items-center justify-between border-b border-sand-200/80 pb-3.5">
        <div className="flex items-center gap-2.5">
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-xl bg-primary-50 text-primary-600 shadow-2xs border border-primary-100/80">
            <Luggage size={12} aria-hidden="true" />
          </span>
          <h3 className="text-base sm:text-lg font-bold text-gray-900 tracking-tight">
            行前必备清单
          </h3>
        </div>
        <span className="rounded-full bg-sand-100 px-2.5 py-0.5 text-[11px] font-medium text-gray-600 border border-sand-200/70">
          共 {totalItems} 项
        </span>
      </div>

      {/* 分类及清单 */}
      <div className="flex-1 space-y-5">
        {groups.map((group, groupIdx) => (
          <div key={`${group.category}-${groupIdx}`} className="space-y-2.5">
            <div className="inline-flex items-center gap-1.5 rounded-lg border border-sand-200/80 bg-sand-50 px-2.5 py-1 text-xs font-bold text-primary-800">
              <span className="h-1.5 w-1.5 rounded-full bg-primary-500" />
              <h4>{group.category}</h4>
            </div>

            <ul className="space-y-2 pl-1">
              {group.items.map((item, itemIdx) => (
                <li
                  key={itemIdx}
                  className="flex items-start gap-2 text-xs sm:text-sm text-gray-700 leading-relaxed break-words"
                >
                  <Check
                    size={10}
                    className="text-primary-500 mt-1 shrink-0"
                    aria-hidden="true"
                  />
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}
