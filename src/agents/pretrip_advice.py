"""Plan-scoped pre-trip packing/tips contracts, builder and sanitizer.

v0.9.9.6 keeps packing signals, note tip evidence and Amap opening facts in
non-interchangeable typed views. Sanitizer defects drop items; they never fail
a publishable core plan. Public TravelTip has no evidence_ref.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field

from src.agents.evidence_strength import StructuredEvidencePayload
from src.agents.schema import (
    PackingChecklistGroup,
    RoutePlan,
    TravelTip,
    TripRequest,
)
from src.agents.weather_advisory import WeatherAdvisoryPayload
from src.config import get_settings

logger = logging.getLogger(__name__)

MAX_PACKING_GROUPS = 4
MAX_ITEMS_PER_GROUP = 3
MAX_TIPS = 4
AMAP_OPENING_SUFFIX = "临出发请以该地点官方当天公告为准。"
AMAP_SOURCE = "amap_poi_v5"
ALLOWED_AMAP_FIELDS = frozenset({"opentime_today", "opentime_week"})
NOTE_TIERS = ("direct_facts", "weak_experience", "risk_only_warnings")
NOTE_TIER_TOKENS = {
    "direct_facts": "direct_facts",
    "weak_experience": "weak_experience",
    "risk_only_warnings": "risk_only_warnings",
}
GENERIC_EQUIPMENT = ("有效身份证件", "常用药和个人护理用品", "充电宝和充电线")
IDENTITY_MARKERS = (
    "老人",
    "儿童",
    "小孩",
    "孩子",
    "亲子",
    "带娃",
    "情侣",
    "夫妻",
    "残障",
    "残疾",
    "轮椅",
    "孕妇",
    "婴儿",
    "宝宝",
    "摄影爱好",
    "摄影师",
)
CONDITIONAL_MARKERS = (
    "若",
    "如果",
    "如遇",
    "假如",
    "要是",
    "可优先",
    "可以考虑",
    "介意",
    "担心",
    "不喜欢",
)
OUTDOOR_TYPE_MARKERS = (
    "park",
    "scenic",
    "attraction",
    "outdoor",
    "hiking",
    "walk",
    "公园",
    "风景",
    "步道",
    "登山",
    "户外",
)
GENERIC_EMPTY_TIP = re.compile(
    r"^(注意|记得|了解一下|出发前看好)(一下|就好)?[。.!！？?]*$"
)
TICKET_RESERVATION_RE = re.compile(
    r"预约|放票|购票|售票|门票资格|票务|取票|订票|无需预约|免预约"
)
PRICE_RE = re.compile(r"(?:\d+(?:\.\d+)?\s*元)|[¥￥]|票价")
NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
NOTE_REF_RE = re.compile(
    r"^note:(?P<place_id>\d+):"
    r"(?P<tier>direct_facts|weak_experience|risk_only_warnings):"
    r"(?P<ordinal>\d+)$"
)
AMAP_REF_RE = re.compile(
    r"^amap:(?P<place_id>\d+):(?P<field>opentime_today|opentime_week)$"
)
SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?])")
WHITESPACE_RE = re.compile(r"\s+")

DROP_INVALID_STRUCTURE = "invalid_structure"
DROP_INVALID_REF = "invalid_ref"
DROP_MIXED_SOURCE = "mixed_source"
DROP_DUPLICATE_REF = "duplicate_ref"
DROP_DUPLICATE_TEXT = "duplicate_text"
DROP_OVERFLOW = "overflow"
DROP_RESERVATION_TICKET = "reservation_ticket"
DROP_HIGH_RISK_UNBACKED = "high_risk_unbacked"
DROP_TONE = "tone_mismatch"
DROP_NOT_ACTIONABLE = "not_actionable"
DROP_IDENTITY_INFERENCE = "identity_inference"
DROP_AMAP_IN_PACKING = "amap_in_packing"
DROP_NOTE_IN_PACKING = "note_in_packing"
DROP_EMPTY = "empty"


def normalize_advice_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return WHITESPACE_RE.sub(" ", value).strip()


def note_evidence_ref(place_id: int, tier: str, ordinal: int) -> str:
    return f"note:{int(place_id)}:{tier}:{int(ordinal)}"


def amap_evidence_ref(place_id: int, field: str) -> str:
    return f"amap:{int(place_id)}:{field}"


class PackingSignals(BaseModel):
    """Writer-facing packing inputs. Never carries note or Amap tip facts."""

    people_count: int = 1
    days: int = 1
    start_date: str | None = None
    preferences: list[str] = Field(default_factory=list)
    notes: str = ""
    explicit_identity_terms: list[str] = Field(default_factory=list)
    place_types: list[str] = Field(default_factory=list)
    daily_stop_counts: list[int] = Field(default_factory=list)
    commute_modes: list[str] = Field(default_factory=list)
    walking_or_outdoor: bool = False
    weather_conditions: list[str] = Field(default_factory=list)
    weather_reminders: list[str] = Field(default_factory=list)
    generic_equipment: list[str] = Field(default_factory=list)
    quantity_notes: list[str] = Field(default_factory=list)


class NoteTipEvidence(BaseModel):
    place_id: int
    place_name: str = ""
    tier: Literal["direct_facts", "weak_experience", "risk_only_warnings"]
    ordinal: int = Field(ge=1)
    text: str
    evidence_ref: str


class AmapTipFact(BaseModel):
    place_id: int
    place_name: str = ""
    amap_poi_id: str
    field: Literal["opentime_today", "opentime_week"]
    value: str
    queried_at: str | None = None
    snapshot_label: str = "当日快照"
    source: Literal["amap_poi_v5"] = AMAP_SOURCE
    evidence_ref: str


class PreTripAdvicePayload(BaseModel):
    packing_signals: PackingSignals = Field(default_factory=PackingSignals)
    note_tip_evidence: list[NoteTipEvidence] = Field(default_factory=list)
    amap_tip_facts: list[AmapTipFact] = Field(default_factory=list)

    def packing_view(self) -> PackingSignals:
        return self.packing_signals

    def note_tip_view(self) -> tuple[NoteTipEvidence, ...]:
        return tuple(self.note_tip_evidence)

    def amap_tip_view(self) -> tuple[AmapTipFact, ...]:
        return tuple(self.amap_tip_facts)

    def authorized_refs(self) -> dict[str, NoteTipEvidence | AmapTipFact]:
        refs: dict[str, NoteTipEvidence | AmapTipFact] = {}
        for item in self.note_tip_evidence:
            refs.setdefault(item.evidence_ref, item)
        for item in self.amap_tip_facts:
            refs.setdefault(item.evidence_ref, item)
        return refs

    def writer_input(self) -> dict[str, Any]:
        """Payload the Writer may see: no timestamps, raw JSON or provider ids."""
        return {
            "packing_signals": self.packing_signals.model_dump(mode="json"),
            "note_tip_evidence": [
                {
                    "place_id": item.place_id,
                    "place_name": item.place_name,
                    "tier": item.tier,
                    "ordinal": item.ordinal,
                    "text": item.text,
                    "evidence_ref": item.evidence_ref,
                }
                for item in self.note_tip_evidence
            ],
            "amap_tip_facts": [
                {
                    "place_id": item.place_id,
                    "place_name": item.place_name,
                    "field": item.field,
                    "value": item.value,
                    "snapshot_label": item.snapshot_label,
                    "evidence_ref": item.evidence_ref,
                }
                for item in self.amap_tip_facts
            ],
        }


def render_pretrip_advice_writer_prompt(payload: PreTripAdvicePayload) -> str:
    """Prompt fragment from writer_input only; no raw timestamps or provider ids."""
    return (
        "行前建议授权（仅本方案 PreTripAdvicePayload.writer_input；"
        "不得使用原始查询时间戳、高德 POI id 或未分级笔记原文）：\n"
        + json.dumps(payload.writer_input(), ensure_ascii=False)
        + "\n规则：packing_checklist 只能组织 packing_signals，禁止 note_tip_evidence"
        " 与 amap_tip_facts；质量目标 3～4 类、每类 2～3 项，最多 4 类、每类最多 3 项。"
        "people_count 只可影响数量，不得推断身份、年龄、关系或行动能力。"
        "travel_tips 没有最少条数；有 1 条合格证据就写 1 条，没有则省略整个字段。"
        "每条 tip 必须且只能包含 title、content、evidence_ref，一条 tip 只引用一个 ref；"
        "note 用 note:<place_id>:<tier>:<ordinal>，amap 用 amap:<place_id>:<field>；"
        "不得混写笔记与高德。"
        "direct_facts 只可近义复述，不得新增数字、范围、因果或适用对象；"
        "weak_experience 与 risk_only_warnings 必须保留条件式语气。"
        "Amap 开放事实只能写入 travel_tips，禁止写入 packing_checklist、"
        "poi_fragments、day_openings 或 summary；不要自行写临出发/当天公告类尾句，"
        "系统会追加唯一复核后缀；出现预约、票务或放票则整条 tip 丢弃。"
        "evidence_ref 不得出现在 packing 或核心正文。"
    )


@dataclass
class AdviceSanitizeMetrics:
    packing_groups_retained: int = 0
    packing_items_retained: int = 0
    tips_retained: int = 0
    dropped_reasons: dict[str, int] = field(default_factory=dict)

    def drop(self, reason: str, count: int = 1) -> None:
        if count <= 0:
            return
        self.dropped_reasons[reason] = self.dropped_reasons.get(reason, 0) + count

    def as_content_free_dict(self) -> dict[str, Any]:
        return {
            "packing_groups_retained": self.packing_groups_retained,
            "packing_items_retained": self.packing_items_retained,
            "tips_retained": self.tips_retained,
            "dropped_reasons": dict(self.dropped_reasons),
        }


@dataclass
class AdviceSanitizeResult:
    packing_checklist: list[PackingChecklistGroup] | None
    travel_tips: list[TravelTip] | None
    metrics: AdviceSanitizeMetrics


def explicit_identity_terms(*texts: Any) -> list[str]:
    blob = " ".join(_flatten_text(texts))
    return [marker for marker in IDENTITY_MARKERS if marker in blob]


def build_pretrip_advice_payload(
    *,
    trip_request: TripRequest,
    route_plan: RoutePlan,
    weather_advisory_payload: WeatherAdvisoryPayload | None = None,
    structured_evidence_payload: StructuredEvidencePayload | None = None,
    amap_facts: Sequence[AmapTipFact | dict[str, Any]] | None = None,
) -> PreTripAdvicePayload:
    """Assemble plan-scoped packing signals and tip evidence. No I/O."""
    locked_places = _locked_places(route_plan)
    locked_ids = {place.place_id for place in locked_places}
    packing = _build_packing_signals(
        trip_request=trip_request,
        route_plan=route_plan,
        locked_places=locked_places,
        weather_advisory_payload=weather_advisory_payload,
    )
    notes = _build_note_tip_evidence(
        structured_evidence_payload,
        locked_ids=locked_ids,
        locked_places=locked_places,
    )
    amap = _build_amap_tip_facts(
        amap_facts,
        locked_ids=locked_ids,
        locked_places=locked_places,
        start_date=trip_request.start_date,
    )
    return PreTripAdvicePayload(
        packing_signals=packing,
        note_tip_evidence=notes,
        amap_tip_facts=amap,
    )


def sanitize_writer_advice(
    packing_raw: Any,
    tips_raw: Any,
    payload: PreTripAdvicePayload | None,
) -> AdviceSanitizeResult:
    metrics = AdviceSanitizeMetrics()
    packing = sanitize_packing_checklist(
        packing_raw,
        payload=payload,
        metrics=metrics,
    )
    tips = sanitize_travel_tips(
        tips_raw,
        payload=payload,
        require_evidence_ref=True,
        metrics=metrics,
    )
    metrics.packing_groups_retained = len(packing or [])
    metrics.packing_items_retained = sum(len(group.items) for group in packing or [])
    metrics.tips_retained = len(tips or [])
    return AdviceSanitizeResult(
        packing_checklist=packing,
        travel_tips=tips,
        metrics=metrics,
    )


def sanitize_public_advice(
    packing_raw: Any,
    tips_raw: Any,
) -> AdviceSanitizeResult:
    metrics = AdviceSanitizeMetrics()
    packing = sanitize_packing_checklist(
        packing_raw,
        payload=None,
        metrics=metrics,
        public_shape=True,
    )
    tips = sanitize_travel_tips(
        tips_raw,
        payload=None,
        require_evidence_ref=False,
        metrics=metrics,
        public_shape=True,
    )
    metrics.packing_groups_retained = len(packing or [])
    metrics.packing_items_retained = sum(len(group.items) for group in packing or [])
    metrics.tips_retained = len(tips or [])
    return AdviceSanitizeResult(
        packing_checklist=packing,
        travel_tips=tips,
        metrics=metrics,
    )


def project_public_plan_advice(
    plan: dict[str, Any] | None,
    *,
    schema_22_enabled: bool | None = None,
) -> tuple[list[PackingChecklistGroup] | None, list[TravelTip] | None]:
    enabled = (
        bool(get_settings().result_schema_22_enabled)
        if schema_22_enabled is None
        else bool(schema_22_enabled)
    )
    if not enabled or not isinstance(plan, dict):
        return None, None
    result = sanitize_public_advice(
        plan.get("packing_checklist"),
        plan.get("travel_tips"),
    )
    return result.packing_checklist, result.travel_tips


def sanitize_packing_checklist(
    raw: Any,
    *,
    payload: PreTripAdvicePayload | None = None,
    metrics: AdviceSanitizeMetrics | None = None,
    public_shape: bool = False,
) -> list[PackingChecklistGroup] | None:
    metrics = metrics or AdviceSanitizeMetrics()
    if raw is None:
        metrics.drop(DROP_EMPTY)
        return None
    if not isinstance(raw, list):
        metrics.drop(DROP_INVALID_STRUCTURE)
        return None
    if not raw:
        metrics.drop(DROP_EMPTY)
        return None

    signals = payload.packing_view() if payload is not None else None
    allowed_identity = set(signals.explicit_identity_terms) if signals else None
    amap_values = _amap_fact_values(payload)
    note_texts = _note_evidence_texts(payload)
    seen_categories: set[str] = set()
    groups: list[PackingChecklistGroup] = []

    for item in raw:
        if len(groups) >= MAX_PACKING_GROUPS:
            metrics.drop(DROP_OVERFLOW)
            continue
        group = _sanitize_packing_group(
            item,
            seen_categories=seen_categories,
            allowed_identity=allowed_identity,
            amap_values=amap_values,
            note_texts=note_texts,
            metrics=metrics,
            public_shape=public_shape,
        )
        if group is None:
            continue
        seen_categories.add(normalize_advice_text(group.category))
        groups.append(group)

    if not groups:
        return None
    return groups


def sanitize_travel_tips(
    raw: Any,
    *,
    payload: PreTripAdvicePayload | None = None,
    require_evidence_ref: bool = True,
    metrics: AdviceSanitizeMetrics | None = None,
    public_shape: bool = False,
) -> list[TravelTip] | None:
    metrics = metrics or AdviceSanitizeMetrics()
    if raw is None:
        metrics.drop(DROP_EMPTY)
        return None
    if not isinstance(raw, list):
        metrics.drop(DROP_INVALID_STRUCTURE)
        return None
    if not raw:
        metrics.drop(DROP_EMPTY)
        return None

    authorized = payload.authorized_refs() if payload is not None else {}
    valid_drafts: list[tuple[str, str, str]] = []
    seen_refs: set[str] = set()

    for item in raw:
        draft = _sanitize_tip_draft(
            item,
            authorized=authorized,
            require_evidence_ref=require_evidence_ref,
            payload=payload,
            metrics=metrics,
            public_shape=public_shape,
        )
        if draft is None:
            continue
        _ref, title, content = draft
        if require_evidence_ref:
            if _ref in seen_refs:
                metrics.drop(DROP_DUPLICATE_REF)
                continue
            seen_refs.add(_ref)
        valid_drafts.append(draft)

    seen_pairs: set[tuple[str, str]] = set()
    retained: list[TravelTip] = []
    for _ref, title, content in valid_drafts:
        pair = (normalize_advice_text(title), normalize_advice_text(content))
        if pair in seen_pairs:
            metrics.drop(DROP_DUPLICATE_TEXT)
            continue
        if len(retained) >= MAX_TIPS:
            metrics.drop(DROP_OVERFLOW)
            continue
        seen_pairs.add(pair)
        retained.append(TravelTip(title=title, content=content))

    if not retained:
        return None
    return retained


def _sanitize_packing_group(
    raw: Any,
    *,
    seen_categories: set[str],
    allowed_identity: set[str] | None,
    amap_values: set[str],
    note_texts: set[str],
    metrics: AdviceSanitizeMetrics,
    public_shape: bool,
) -> PackingChecklistGroup | None:
    if not isinstance(raw, dict):
        metrics.drop(DROP_INVALID_STRUCTURE)
        return None
    category = normalize_advice_text(raw.get("category"))
    if not category:
        metrics.drop(DROP_INVALID_STRUCTURE)
        return None
    if category in seen_categories:
        metrics.drop(DROP_DUPLICATE_TEXT)
        return None
    if allowed_identity is not None:
        for marker in IDENTITY_MARKERS:
            if marker in category and marker not in allowed_identity:
                metrics.drop(DROP_IDENTITY_INFERENCE)
                return None
    items_raw = raw.get("items")
    if not isinstance(items_raw, list):
        metrics.drop(DROP_INVALID_STRUCTURE)
        return None

    seen_items: set[str] = set()
    items: list[str] = []
    for value in items_raw:
        text = normalize_advice_text(value)
        if not text:
            metrics.drop(DROP_INVALID_STRUCTURE)
            continue
        if text in seen_items:
            metrics.drop(DROP_DUPLICATE_TEXT)
            continue
        drop_reason = _packing_item_drop_reason(
            text,
            allowed_identity=allowed_identity,
            amap_values=amap_values,
            note_texts=note_texts,
            public_shape=public_shape,
        )
        if drop_reason:
            metrics.drop(drop_reason)
            continue
        if len(items) >= MAX_ITEMS_PER_GROUP:
            metrics.drop(DROP_OVERFLOW)
            continue
        seen_items.add(text)
        items.append(text)
    if not items:
        metrics.drop(DROP_EMPTY)
        return None
    return PackingChecklistGroup(category=category, items=items)


def _packing_item_drop_reason(
    text: str,
    *,
    allowed_identity: set[str] | None,
    amap_values: set[str],
    note_texts: set[str],
    public_shape: bool,
) -> str | None:
    if AMAP_OPENING_SUFFIX in text or "临出发请以该地点官方当天公告为准" in text:
        return DROP_AMAP_IN_PACKING
    if any(value and value in text for value in amap_values):
        return DROP_AMAP_IN_PACKING
    if any(note and note in text for note in note_texts):
        return DROP_NOTE_IN_PACKING
    if allowed_identity is not None:
        for marker in IDENTITY_MARKERS:
            if marker in text and marker not in allowed_identity:
                return DROP_IDENTITY_INFERENCE
    if public_shape:
        return None
    if TICKET_RESERVATION_RE.search(text) or PRICE_RE.search(text):
        return DROP_HIGH_RISK_UNBACKED
    return None


def _sanitize_tip_draft(
    raw: Any,
    *,
    authorized: dict[str, NoteTipEvidence | AmapTipFact],
    require_evidence_ref: bool,
    payload: PreTripAdvicePayload | None,
    metrics: AdviceSanitizeMetrics,
    public_shape: bool,
) -> tuple[str, str, str] | None:
    if not isinstance(raw, dict):
        metrics.drop(DROP_INVALID_STRUCTURE)
        return None
    title = normalize_advice_text(raw.get("title"))
    content = normalize_advice_text(raw.get("content"))
    if not title or not content:
        metrics.drop(DROP_INVALID_STRUCTURE)
        return None
    extra_refs = raw.get("evidence_refs")
    if extra_refs not in (None, "", []):
        metrics.drop(DROP_MIXED_SOURCE)
        return None

    ref = normalize_advice_text(raw.get("evidence_ref"))
    if require_evidence_ref:
        if not ref:
            metrics.drop(DROP_INVALID_REF)
            return None
        evidence = authorized.get(ref)
        if evidence is None:
            metrics.drop(DROP_INVALID_REF)
            return None
        mixed_reason = _mixed_source_reason(ref, content, payload)
        if mixed_reason:
            metrics.drop(mixed_reason)
            return None
        if isinstance(evidence, AmapTipFact):
            if TICKET_RESERVATION_RE.search(content):
                metrics.drop(DROP_RESERVATION_TICKET)
                return None
            content = _apply_amap_suffix(content)
        else:
            tone_reason = _note_tone_drop_reason(evidence, content)
            if tone_reason:
                metrics.drop(tone_reason)
                return None
            if _unbacked_reservation_ticket(content, evidence.text):
                metrics.drop(DROP_RESERVATION_TICKET)
                return None
            if _unbacked_high_risk(content, evidence.text):
                metrics.drop(DROP_HIGH_RISK_UNBACKED)
                return None
        if not _is_actionable(content):
            metrics.drop(DROP_NOT_ACTIONABLE)
            return None
        return ref, title, content

    # Public projection: already-sanitized persisted advice keeps title/content.
    if not _is_actionable(content):
        metrics.drop(DROP_NOT_ACTIONABLE)
        return None
    return ref or f"public:{len(title)}:{len(content)}", title, content


def _mixed_source_reason(
    ref: str,
    content: str,
    payload: PreTripAdvicePayload | None,
) -> str | None:
    if payload is None:
        return None
    note_match = NOTE_REF_RE.fullmatch(ref)
    amap_match = AMAP_REF_RE.fullmatch(ref)
    if note_match and amap_match:
        return DROP_MIXED_SOURCE
    if note_match:
        for fact in payload.amap_tip_facts:
            if fact.value and fact.value in content:
                return DROP_MIXED_SOURCE
            if AMAP_OPENING_SUFFIX in content:
                return DROP_MIXED_SOURCE
        return None
    if amap_match:
        for note in payload.note_tip_evidence:
            if note.text and note.text in content:
                return DROP_MIXED_SOURCE
        return None
    return DROP_INVALID_REF


def _note_tone_drop_reason(evidence: NoteTipEvidence, content: str) -> str | None:
    if evidence.tier == "direct_facts":
        extra_numbers = set(NUMBER_RE.findall(content)) - set(
            NUMBER_RE.findall(evidence.text)
        )
        if extra_numbers:
            return DROP_HIGH_RISK_UNBACKED
        return None
    if not any(marker in content for marker in CONDITIONAL_MARKERS):
        return DROP_TONE
    return None


def _ticket_reservation_markers(text: str) -> set[str]:
    return {match.group(0) for match in TICKET_RESERVATION_RE.finditer(text)}


def _unbacked_reservation_ticket(content: str, evidence_text: str) -> bool:
    claimed = _ticket_reservation_markers(content)
    if not claimed:
        return False
    authorized = _ticket_reservation_markers(evidence_text)
    return not claimed.issubset(authorized)


def _unbacked_high_risk(content: str, evidence_text: str) -> bool:
    return bool(PRICE_RE.search(content) and not PRICE_RE.search(evidence_text))


def _is_actionable(content: str) -> bool:
    text = normalize_advice_text(content)
    if len(text) < 8:
        return False
    return not GENERIC_EMPTY_TIP.fullmatch(text)


def _apply_amap_suffix(content: str) -> str:
    text = normalize_advice_text(content)
    parts = [part.strip() for part in SENTENCE_SPLIT_RE.split(text) if part.strip()]
    if not parts:
        parts = [text] if text else []
    while parts and _is_recheck_tail(parts[-1]):
        parts.pop()
    rebuilt = "".join(
        part if part.endswith(("。", "！", "？", "!", "?")) else f"{part}。"
        for part in parts
    ).strip()
    if not rebuilt:
        rebuilt = text
    if rebuilt.endswith(AMAP_OPENING_SUFFIX):
        return rebuilt
    if not rebuilt.endswith(("。", "！", "？", "!", "?")):
        rebuilt = f"{rebuilt}。"
    return f"{rebuilt}{AMAP_OPENING_SUFFIX}"


def _is_recheck_tail(sentence: str) -> bool:
    text = normalize_advice_text(sentence)
    compact = text.rstrip("。.!！？? ")
    canonical = AMAP_OPENING_SUFFIX.rstrip("。")
    if text == AMAP_OPENING_SUFFIX or compact == canonical:
        return True
    return "临出发" in text or "当天公告" in text


def _build_packing_signals(
    *,
    trip_request: TripRequest,
    route_plan: RoutePlan,
    locked_places: list[Any],
    weather_advisory_payload: WeatherAdvisoryPayload | None,
) -> PackingSignals:
    people_count = max(1, int(trip_request.people_count or 1))
    place_types = _unique(
        [
            str(place.place_type).strip()
            for place in locked_places
            if str(getattr(place, "place_type", "") or "").strip()
        ]
    )
    daily_stop_counts = [
        len(day_group.places) for day_group in route_plan.day_groups
    ]
    commute_modes = _unique(
        [
            str(leg.mode).strip()
            for day_group in route_plan.day_groups
            for leg in day_group.commute_legs
            if str(getattr(leg, "mode", "") or "").strip()
        ]
    )
    walking_or_outdoor = "walking" in commute_modes or any(
        _looks_outdoor(place_type) for place_type in place_types
    ) or any(
        marker in " ".join(trip_request.preferences)
        for marker in ("citywalk", "步行", "户外")
    )
    weather_conditions: list[str] = []
    weather_reminders: list[str] = []
    if weather_advisory_payload is not None and weather_advisory_payload.is_ok():
        weather_conditions = _unique(
            [
                condition
                for day in weather_advisory_payload.days
                for condition in day.conditions
                if normalize_advice_text(condition)
            ]
        )
        weather_reminders = _unique(
            [
                reminder
                for day in weather_advisory_payload.days
                for reminder in day.authorized_reminders
                if normalize_advice_text(reminder)
            ]
        )
    identity_terms = explicit_identity_terms(
        trip_request.preferences,
        trip_request.notes,
    )
    return PackingSignals(
        people_count=people_count,
        days=max(1, int(trip_request.days or 1)),
        start_date=trip_request.start_date,
        preferences=list(trip_request.preferences),
        notes=trip_request.notes or "",
        explicit_identity_terms=identity_terms,
        place_types=place_types,
        daily_stop_counts=daily_stop_counts,
        commute_modes=commute_modes,
        walking_or_outdoor=walking_or_outdoor,
        weather_conditions=weather_conditions,
        weather_reminders=weather_reminders,
        generic_equipment=list(GENERIC_EQUIPMENT),
        quantity_notes=[f"雨具和饮水可按 {people_count} 人准备"],
    )


def _build_note_tip_evidence(
    payload: StructuredEvidencePayload | None,
    *,
    locked_ids: set[int],
    locked_places: list[Any],
) -> list[NoteTipEvidence]:
    if payload is None:
        return []
    names = {
        place.place_id: str(place.name or "")
        for place in locked_places
    }
    items: list[NoteTipEvidence] = []
    for place in payload.places:
        if place.place_id not in locked_ids:
            continue
        for tier in NOTE_TIERS:
            texts = getattr(place, tier, None) or []
            ordinal = 0
            for text in texts:
                value = normalize_advice_text(text)
                if not value:
                    continue
                ordinal += 1
                items.append(
                    NoteTipEvidence(
                        place_id=place.place_id,
                        place_name=names.get(place.place_id, place.name),
                        tier=tier,  # type: ignore[arg-type]
                        ordinal=ordinal,
                        text=value,
                        evidence_ref=note_evidence_ref(
                            place.place_id,
                            NOTE_TIER_TOKENS[tier],
                            ordinal,
                        ),
                    )
                )
    return items


def _build_amap_tip_facts(
    raw_facts: Sequence[AmapTipFact | dict[str, Any]] | None,
    *,
    locked_ids: set[int],
    locked_places: list[Any],
    start_date: str | None,
) -> list[AmapTipFact]:
    if not raw_facts:
        return []
    names = {
        place.place_id: str(place.name or "")
        for place in locked_places
    }
    seen_refs: set[str] = set()
    facts: list[AmapTipFact] = []
    default_label = f"{start_date} 快照" if start_date else "当日快照"
    for raw in raw_facts:
        fact = _coerce_amap_fact(raw, default_label=default_label)
        if fact is None:
            continue
        if fact.place_id not in locked_ids:
            continue
        if fact.field not in ALLOWED_AMAP_FIELDS:
            continue
        if not fact.amap_poi_id or not fact.value:
            continue
        if fact.evidence_ref in seen_refs:
            continue
        seen_refs.add(fact.evidence_ref)
        if not fact.place_name:
            fact = fact.model_copy(
                update={"place_name": names.get(fact.place_id, "")}
            )
        facts.append(fact)
    return facts


def _coerce_amap_fact(
    raw: AmapTipFact | dict[str, Any],
    *,
    default_label: str,
) -> AmapTipFact | None:
    if isinstance(raw, AmapTipFact):
        value = normalize_advice_text(raw.value)
        poi_id = normalize_advice_text(raw.amap_poi_id)
        if not value or not poi_id or raw.field not in ALLOWED_AMAP_FIELDS:
            return None
        snapshot = raw.snapshot_label or _snapshot_label(raw.queried_at, default_label)
        return raw.model_copy(
            update={
                "value": value,
                "amap_poi_id": poi_id,
                "source": AMAP_SOURCE,
                "snapshot_label": snapshot,
                "evidence_ref": amap_evidence_ref(raw.place_id, raw.field),
            }
        )
    if not isinstance(raw, dict):
        return None
    try:
        place_id = int(raw.get("place_id"))
    except (TypeError, ValueError):
        return None
    field_name = normalize_advice_text(raw.get("field"))
    value = normalize_advice_text(raw.get("value"))
    poi_id = normalize_advice_text(raw.get("amap_poi_id"))
    if field_name not in ALLOWED_AMAP_FIELDS or not value or not poi_id:
        return None
    queried_at = normalize_advice_text(raw.get("queried_at")) or None
    return AmapTipFact(
        place_id=place_id,
        place_name=normalize_advice_text(raw.get("place_name")),
        amap_poi_id=poi_id,
        field=field_name,  # type: ignore[arg-type]
        value=value,
        queried_at=queried_at,
        snapshot_label=_snapshot_label(queried_at, default_label),
        source=AMAP_SOURCE,
        evidence_ref=amap_evidence_ref(place_id, field_name),
    )


def _snapshot_label(queried_at: str | None, default_label: str) -> str:
    if queried_at and len(queried_at) >= 10 and queried_at[4] == "-":
        return f"{queried_at[:10]} 快照"
    return default_label


def _locked_places(route_plan: RoutePlan) -> list[Any]:
    seen: set[int] = set()
    places: list[Any] = []
    for day_group in route_plan.day_groups:
        for place in day_group.places:
            if place.place_id in seen:
                continue
            seen.add(place.place_id)
            places.append(place)
    return places


def _amap_fact_values(payload: PreTripAdvicePayload | None) -> set[str]:
    if payload is None:
        return set()
    return {
        normalize_advice_text(fact.value)
        for fact in payload.amap_tip_facts
        if normalize_advice_text(fact.value)
    }


def _note_evidence_texts(payload: PreTripAdvicePayload | None) -> set[str]:
    if payload is None:
        return set()
    return {
        normalize_advice_text(item.text)
        for item in payload.note_tip_evidence
        if normalize_advice_text(item.text)
    }


def _looks_outdoor(place_type: str) -> bool:
    lowered = place_type.lower()
    return any(marker.lower() in lowered for marker in OUTDOOR_TYPE_MARKERS)


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = normalize_advice_text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _flatten_text(values: Sequence[Any]) -> list[str]:
    texts: list[str] = []
    for value in values:
        if isinstance(value, str):
            if value.strip():
                texts.append(value)
            continue
        if isinstance(value, (list, tuple)):
            texts.extend(_flatten_text(value))
    return texts
