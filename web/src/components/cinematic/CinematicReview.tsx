import { useState } from "react";
import { Edit3, MapPin, Building, FileText } from "lucide-react";
import type { RequestedCommuteMode } from "@/types/form";
import { formatDateLabel } from "@/utils/cinematicDate";
import {
  CINEMATIC_COMMUTE_OPTIONS,
} from "@/types/cinematic";
import {
  CinematicAccommodationModal,
  CinematicNotesModal,
} from "./CinematicModals";

interface CinematicReviewProps {
  cityName: string;
  startDate: string;
  endDate: string;
  days: number;
  companion: string;
  peopleCount: number;
  commuteMode: RequestedCommuteMode;
  preferences: string[];
  accommodationName?: string;
  notes?: string;
  fromCity?: string;
  avoid?: string[];
  dailyStart?: string;
  dailyEnd?: string;
  budget?: number;
  selectedPois?: { id: number; name: string }[];
  isSubmitting?: boolean;
  onSaveAccommodation: (name: string) => void;
  onSaveNotesAndFromCity: (notes: string, fromCity: string) => void;
  onClearExtraSettings?: () => void;
  onBackToMap: () => void;
  onOpenPoiPicker: () => void;
  onSubmit: () => void;
}

export function CinematicReview({
  cityName,
  startDate,
  endDate,
  days,
  companion,
  peopleCount,
  commuteMode,
  preferences,
  accommodationName,
  notes,
  fromCity,
  avoid,
  dailyStart,
  dailyEnd,
  budget,
  selectedPois = [],
  isSubmitting = false,
  onSaveAccommodation,
  onSaveNotesAndFromCity,
  onClearExtraSettings,
  onBackToMap,
  onOpenPoiPicker,
  onSubmit,
}: CinematicReviewProps) {
  const [accModalOpen, setAccModalOpen] = useState(false);
  const [notesModalOpen, setNotesModalOpen] = useState(false);

  const commuteLabel =
    CINEMATIC_COMMUTE_OPTIONS.find((c) => c.value === commuteMode)?.label || "公共交通";

  const dateSummary =
    startDate && endDate
      ? `${formatDateLabel(startDate)} - ${formatDateLabel(endDate)} (${days} 天)`
      : "日期未定";

  const hasExtraSettings =
    (avoid && avoid.length > 0) ||
    Boolean(dailyStart) ||
    Boolean(dailyEnd) ||
    typeof budget === "number";

  return (
    <div className="cmp-review">
      <div className="cmp-review-header">
        <strong>{cityName}</strong>
        <span>{dateSummary}</span>
      </div>

      <div className="cmp-review-details">
        <div>
          <span>同伴：</span>
          {companion ? `${companion}，` : ""}
          {peopleCount} 人同行
        </div>
        <div>
          <span>出行方式：</span>
          {commuteLabel}
        </div>
        <div>
          <span>偏好：</span>
          {preferences.length > 0
            ? preferences.join("、")
            : "无"}
        </div>
        {accommodationName && (
          <div>
            <span>住宿：</span>
            {accommodationName}
          </div>
        )}
        {fromCity && (
          <div>
            <span>出发城市：</span>
            {fromCity}
          </div>
        )}
        {notes && (
          <div>
            <span>备注：</span>
            {notes}
          </div>
        )}
      </div>

      {hasExtraSettings && (
        <div className="cmp-review-extra-note" role="note">
          <span>已应用部分默认偏好</span>
          {onClearExtraSettings && (
            <button
              type="button"
              className="cmp-text-button"
              style={{ padding: "2px 6px", fontSize: "12px" }}
              onClick={onClearExtraSettings} disabled={isSubmitting}
            >
              清除
            </button>
          )}
        </div>
      )}

      <div className="cmp-review-entries">
        <button
          type="button"
          className="cmp-review-entry-btn"
          onClick={() => setAccModalOpen(true)} disabled={isSubmitting}
        >
          <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <Building size={14} />
            {accommodationName ? "修改住宿" : "添加住宿（可选）"}
          </span>
          <Edit3 size={13} style={{ opacity: 0.6 }} />
        </button>

        <button
          type="button"
          className="cmp-review-entry-btn"
          onClick={() => setNotesModalOpen(true)} disabled={isSubmitting}
        >
          <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <FileText size={14} />
            {notes || fromCity ? "修改备注/要求" : "添加更多要求（可选）"}
          </span>
          <Edit3 size={13} style={{ opacity: 0.6 }} />
        </button>

        <button
          type="button"
          className={`cmp-review-entry-btn ${selectedPois.length > 0 ? 'has-pois' : ''}`}
          onClick={onOpenPoiPicker} disabled={isSubmitting}
        >
          <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <MapPin size={14} />
            {selectedPois.length > 0 ? `已选 ${selectedPois.length} 个必去地点` : '添加必去地点（最多 5 个）'}
          </span>
          <Edit3 size={13} style={{ opacity: 0.6 }} />
        </button>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 8 }}>
        <button
          type="button"
          className="cmp-continue"
          onClick={onSubmit} disabled={isSubmitting}
        >
          开始生成
        </button>
        <button
          type="button"
          className="cmp-text-button"
          onClick={onBackToMap} disabled={isSubmitting}
        >
          重新选择
        </button>
      </div>

      <CinematicAccommodationModal
        initialValue={accommodationName || ""}
        isOpen={accModalOpen}
        onClose={() => setAccModalOpen(false)}
        onSave={onSaveAccommodation}
      />
      
      <CinematicNotesModal
        initialNotes={notes || ""}
        initialFromCity={fromCity || ""}
        isOpen={notesModalOpen}
        onClose={() => setNotesModalOpen(false)}
        onSave={onSaveNotesAndFromCity}
      />
    </div>
  );
}

