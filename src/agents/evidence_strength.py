"""Deterministic evidence-strength classification for Writer authorization."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from src.agents.schema import (
    CandidatePlace,
    CompositionBlueprint,
    RetrievalResult,
    RoutePlan,
)

EvidenceSource = Literal["top_reason", "warning", "evidence_summary"]
EvidenceStrength = Literal[
    "direct_fact",
    "weak_experience",
    "risk_only_warning",
    "not_authorized",
    "omitted",
]
EvidenceRuleLayer = Literal[
    "L0_NOT_AUTHORIZED",
    "L1_RISK_ONLY",
    "L2_DIRECT_FACT",
    "L3_WEAK_EXPERIENCE",
    "L4_OMITTED",
]
EvidenceRiskLevel = Literal["low", "medium", "high"]

PAYLOAD_VERSION = "v0.7.4"


@dataclass(frozen=True)
class EvidenceSignal:
    text: str
    source: EvidenceSource
    strength: EvidenceStrength
    reason: str
    marker: str = ""
    rule_id: str = ""
    rule_layer: EvidenceRuleLayer = "L4_OMITTED"
    risk_level: EvidenceRiskLevel = "low"


@dataclass(frozen=True)
class EvidenceRule:
    rule_id: str
    layer: EvidenceRuleLayer
    strength: EvidenceStrength
    reason: str
    markers: tuple[str, ...]
    risk_level: EvidenceRiskLevel = "low"
    requires_absence: tuple[str, ...] = ()


@dataclass(frozen=True)
class MandatoryMentionPolicy:
    mandatory_mention: bool = False
    blueprint_role: str = ""
    authorized_actions: tuple[str, ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class DeterministicActionContract:
    plan_index: int
    day: int
    place_id: int
    place_name: str
    blueprint_role: str = ""
    meal_slot: str | None = None
    authorized_actions: tuple[str, ...] = ()
    reason: str = "locked_route_stop"

    @property
    def key(self) -> tuple[int, int, int]:
        return (self.plan_index, self.day, self.place_id)

    def mention_policy(self) -> MandatoryMentionPolicy:
        return MandatoryMentionPolicy(
            mandatory_mention=True,
            blueprint_role=self.blueprint_role,
            authorized_actions=self.authorized_actions,
            reason=self.reason,
        )


@dataclass(frozen=True)
class PlaceEvidencePayload:
    place_id: int
    name: str
    place_type: str
    direct_facts: list[str] = field(default_factory=list)
    weak_experience: list[str] = field(default_factory=list)
    risk_only_warnings: list[str] = field(default_factory=list)
    not_authorized_reasons: dict[str, int] = field(default_factory=dict)
    omitted_count: int = 0
    mandatory_mention_policy: MandatoryMentionPolicy = field(
        default_factory=MandatoryMentionPolicy
    )


@dataclass(frozen=True)
class StructuredEvidencePayload:
    version: str
    places: list[PlaceEvidencePayload]
    action_plan: list[DeterministicActionContract] = field(default_factory=list)
    classifier_fail_closed: bool = True
    metrics: dict[str, Any] = field(default_factory=dict)

    def for_place_ids(self, place_ids: set[int]) -> "StructuredEvidencePayload":
        return StructuredEvidencePayload(
            version=self.version,
            places=[place for place in self.places if place.place_id in place_ids],
            action_plan=[
                contract
                for contract in self.action_plan
                if contract.place_id in place_ids
            ],
            classifier_fail_closed=self.classifier_fail_closed,
            metrics=self.metrics,
        )

    def action_contract(
        self,
        *,
        plan_index: int,
        day: int,
        place_id: int,
    ) -> DeterministicActionContract | None:
        key = (plan_index, day, place_id)
        return next(
            (contract for contract in self.action_plan if contract.key == key),
            None,
        )

    def for_route_plan(
        self,
        route_plan: RoutePlan,
        *,
        plan_index: int | None = None,
    ) -> "StructuredEvidencePayload":
        route_keys = {
            (day_group.day, place.place_id)
            for day_group in route_plan.day_groups
            for place in day_group.places
        }
        resolved_plan_index = plan_index
        if resolved_plan_index is None:
            candidate_indexes = {
                contract.plan_index
                for contract in self.action_plan
                if (contract.day, contract.place_id) in route_keys
            }
            if len(candidate_indexes) == 1:
                resolved_plan_index = next(iter(candidate_indexes))
            elif len(candidate_indexes) > 1:
                raise ValueError(
                    "action_plan_index_required_for_ambiguous_route"
                )

        selected_contracts = [
            contract
            for contract in self.action_plan
            if (
                (resolved_plan_index is None or contract.plan_index == resolved_plan_index)
                and (contract.day, contract.place_id) in route_keys
            )
        ]
        contract_by_place_id = {
            contract.place_id: contract
            for contract in selected_contracts
        }
        place_ids = {place_id for _, place_id in route_keys}
        scoped_places = [
            replace(
                place,
                mandatory_mention_policy=(
                    contract_by_place_id[place.place_id].mention_policy()
                    if place.place_id in contract_by_place_id
                    else place.mandatory_mention_policy
                ),
            )
            for place in self.places
            if place.place_id in place_ids
        ]
        return StructuredEvidencePayload(
            version=self.version,
            places=scoped_places,
            action_plan=selected_contracts,
            classifier_fail_closed=self.classifier_fail_closed,
            metrics=self.metrics,
        )

    def metrics_summary(self) -> dict[str, Any]:
        summary = {
            "version": self.version,
            "direct_fact_count": 0,
            "weak_experience_count": 0,
            "risk_only_warning_count": 0,
            "not_authorized_count": 0,
            "omitted_count": 0,
            "mandatory_mention_count": 0,
            "authorized_action_count": 0,
            "action_contract_count": len(self.action_plan),
            "mandatory_blueprint_roles": [],
            "not_authorized_reasons": [],
            "classifier_fail_closed": self.classifier_fail_closed,
        }
        reasons: dict[str, int] = {}
        blueprint_roles: set[str] = set()
        for place in self.places:
            summary["direct_fact_count"] += len(place.direct_facts)
            summary["weak_experience_count"] += len(place.weak_experience)
            summary["risk_only_warning_count"] += len(place.risk_only_warnings)
            summary["omitted_count"] += place.omitted_count
            if not self.action_plan:
                if place.mandatory_mention_policy.mandatory_mention:
                    summary["mandatory_mention_count"] += 1
                summary["authorized_action_count"] += len(
                    place.mandatory_mention_policy.authorized_actions
                )
                if place.mandatory_mention_policy.blueprint_role:
                    blueprint_roles.add(
                        place.mandatory_mention_policy.blueprint_role
                    )
            for reason, count in place.not_authorized_reasons.items():
                summary["not_authorized_count"] += count
                reasons[reason] = reasons.get(reason, 0) + count
        if self.action_plan:
            summary["mandatory_mention_count"] = len(self.action_plan)
            summary["authorized_action_count"] = sum(
                len(contract.authorized_actions)
                for contract in self.action_plan
            )
            blueprint_roles.update(
                contract.blueprint_role
                for contract in self.action_plan
                if contract.blueprint_role
            )
        summary["not_authorized_reasons"] = sorted(reasons)
        summary["mandatory_blueprint_roles"] = sorted(blueprint_roles)
        return summary


_DIRECT_FACT_MARKERS = (
    "免费",
    "开放",
    "不用门票",
    "无门票",
    "分钟",
    "min",
    "米",
    "公里",
    "km",
    "步行",
    "走几步",
    "附近",
    "下坡",
    "上坡",
    "台阶",
    "坡路",
    "电梯",
    "索道",
    "咖啡",
    "休息",
    "午餐",
    "晚餐",
    "小吃",
    "轻食",
    # Spatial structure / facility markers (objective, verifiable layout facts)
    "包括",
    "广场",
    "湖",
    "滨水",
    "运动中心",
    "展区",
    "展厅",
    "楼层",
    "区域",
    "入口",
    "出口",
    "空间",
    "园内",
    "主入口",
    "侧门",
    "南门",
    "北门",
    "东门",
    "西门",
    "园区",
    "馆内",
    "室内",
    "室外",
    "大厅",
    "中庭",
    "环湖",
    "湖边",
    "湖畔",
    "岸边",
    "步道",
    "栈道",
    "通道",
    "连廊",
    "停车场",
    "卫生间",
    "洗手间",
    "游客中心",
    "服务中心",
)

_DIRECT_FACT_BLOCKERS = (
    "适合",
    "很",
    "氛围",
    "值得",
    "推荐",
    "宝藏",
    "出片",
    "打卡",
    "沉浸",
)

_PHOTO_CONTEXT_MARKERS = (
    "步行",
    "走几步",
    "路过",
    "经过",
    "顺路",
    "停留",
)

_PHOTO_MARKERS = (
    "拍照",
    "拍到",
    "看见",
    "看到",
    "视角",
)

_WEAK_EXPERIENCE_MARKERS = (
    "安静",
    "慢慢逛",
    "放慢",
    "轻松",
    "氛围",
    "适合休息",
    "适合咖啡",
    "适合散步",
    "适合citywalk",
    "适合 citywalk",
    "顺路停留",
)

_RISK_MARKERS = (
    "人多",
    "排队",
    "拥挤",
    "虫",
    "晒",
    "雨",
    "滑",
    "坡多",
    "绕路",
    "施工",
    "关闭",
    "维护",
    "避开",
    "注意",
)

_QUEUE_RISK_MARKERS = (
    "经常排队",
    "常常排队",
    "很多人排队",
    "排队人",
)

_MARKETING_MARKERS = (
    "必打卡",
    "很出片",
    "超级出片",
    "出片",
    "最佳机位",
    "宝藏",
    "本地人推荐",
    "当地人推荐",
    "博主推荐",
    "最火",
    "热门",
    "老字号",
    "招牌",
    "不用预约",
    "无需预约",
    "票价",
    "营业时间",
    "必去",
    "值得",
    "推荐",
    "top",
    "best",
)

_UNAUTHORIZED_SOFT_MARKERS = (
    "很值得",
    "值得",
    "很有氛围",
    "氛围感",
    "感受氛围",
    "老城氛围",
    "沉浸体验",
    "适合沉浸",
    "经典路线",
    "经典机位",
    "经典拍照机位",
    "宝藏小店",
    "宝藏",
    "很出片",
    "超级出片",
    "出片",
    "随手拍都有大片感",
    "大片感",
    "拍照记录",
    "拍照留念",
    "本地人爱去",
    "本地人推荐",
    "当地人推荐",
    "根据自己状态",
    "灵活加减",
    "节奏可以自己说了算",
)

_FORBIDDEN_EVALUATION_WORDS = (
    "推荐",
    "值得",
    "很好",
    "亮点",
    "必去",
    "必打卡",
    "宝藏",
    "隐藏宝藏",
    "hidden gem",
    "must-go",
)

_OBSERVED_POPULARITY_MARKERS = (
    "客流",
    "人气",
)

_EVIDENCE_RULES: tuple[EvidenceRule, ...] = (
    EvidenceRule(
        rule_id="l0_marketing_or_evaluation_phrase",
        layer="L0_NOT_AUTHORIZED",
        strength="not_authorized",
        reason="marketing_phrase",
        markers=(*_UNAUTHORIZED_SOFT_MARKERS, *_MARKETING_MARKERS),
        risk_level="high",
    ),
    EvidenceRule(
        rule_id="l1_queue_risk_signal",
        layer="L1_RISK_ONLY",
        strength="risk_only_warning",
        reason="risk_marker",
        markers=_QUEUE_RISK_MARKERS,
        risk_level="medium",
    ),
    EvidenceRule(
        rule_id="l1_risk_signal",
        layer="L1_RISK_ONLY",
        strength="risk_only_warning",
        reason="risk_marker",
        markers=_RISK_MARKERS,
        risk_level="medium",
    ),
    EvidenceRule(
        rule_id="l0_photo_claim_without_route_clue",
        layer="L0_NOT_AUTHORIZED",
        strength="not_authorized",
        reason="photo_claim_without_route_clue",
        markers=_PHOTO_MARKERS,
        risk_level="medium",
    ),
    EvidenceRule(
        rule_id="l2_direct_fact_marker",
        layer="L2_DIRECT_FACT",
        strength="direct_fact",
        reason="direct_fact_marker",
        markers=_DIRECT_FACT_MARKERS,
        risk_level="medium",
        requires_absence=_DIRECT_FACT_BLOCKERS,
    ),
    EvidenceRule(
        rule_id="l3_observed_popularity",
        layer="L3_WEAK_EXPERIENCE",
        strength="weak_experience",
        reason="observed_popularity",
        markers=_OBSERVED_POPULARITY_MARKERS,
        risk_level="medium",
    ),
    EvidenceRule(
        rule_id="l3_safe_weak_experience_marker",
        layer="L3_WEAK_EXPERIENCE",
        strength="weak_experience",
        reason="safe_weak_marker",
        markers=_WEAK_EXPERIENCE_MARKERS,
        risk_level="low",
    ),
)

_SUMMARY_SPLIT_RE = re.compile(r"[;；。.\n]+")


def _clean_text(value: Any) -> str:
    text = str(value or "").strip()
    return re.sub(r"\s+", " ", text)


def _reason_text(item: Any) -> str:
    if isinstance(item, dict):
        return _clean_text(item.get("reason") or item.get("text") or item.get("summary"))
    return _clean_text(item)


def _contains_any(text: str, markers: tuple[str, ...]) -> str:
    lower = text.lower()
    for marker in markers:
        if marker.lower() in lower:
            return marker
    return ""


def _rule_match(text: str, rule: EvidenceRule) -> str:
    marker = _contains_any(text, rule.markers)
    if not marker:
        return ""
    if rule.requires_absence and _contains_any(text, rule.requires_absence):
        return ""
    if (
        rule.rule_id == "l0_photo_claim_without_route_clue"
        and _contains_any(text, _PHOTO_CONTEXT_MARKERS)
    ):
        return ""
    return marker


def _signal_from_rule(
    *,
    text: str,
    source: EvidenceSource,
    rule: EvidenceRule,
    marker: str,
) -> EvidenceSignal:
    return EvidenceSignal(
        text=text,
        source=source,
        strength=rule.strength,
        reason=rule.reason,
        marker=marker,
        rule_id=rule.rule_id,
        rule_layer=rule.layer,
        risk_level=rule.risk_level,
    )


def _classify_signal(text: str, source: EvidenceSource) -> EvidenceSignal:
    text = _clean_text(text)
    if not text:
        return EvidenceSignal(
            text="",
            source=source,
            strength="omitted",
            reason="empty_signal",
            rule_id="l4_empty_signal",
            rule_layer="L4_OMITTED",
        )

    if source == "warning":
        return EvidenceSignal(
            text=text,
            source=source,
            strength="risk_only_warning",
            reason="warning_source",
            marker="warning",
            rule_id="l1_warning_source",
            rule_layer="L1_RISK_ONLY",
            risk_level="medium",
        )

    for rule in _EVIDENCE_RULES:
        marker = _rule_match(text, rule)
        if marker:
            return _signal_from_rule(
                text=text,
                source=source,
                rule=rule,
                marker=marker,
            )

    return EvidenceSignal(
        text=text,
        source=source,
        strength="omitted",
        reason="unknown_signal",
        rule_id="l4_unknown_signal",
        rule_layer="L4_OMITTED",
    )


def _add_count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _dedupe_limited(values: list[str], limit: int = 3) -> list[str]:
    result: list[str] = []
    for value in values:
        value = _clean_text(value)
        if value and value not in result:
            result.append(value[:180])
        if len(result) >= limit:
            break
    return result


def _place_payload(
    place: CandidatePlace,
    mandatory_mention_policy: MandatoryMentionPolicy | None = None,
) -> tuple[PlaceEvidencePayload, list[EvidenceSignal]]:
    direct_facts: list[str] = []
    weak_experience: list[str] = []
    risk_only_warnings: list[str] = []
    not_authorized_reasons: dict[str, int] = {}
    omitted_count = 0
    signals: list[EvidenceSignal] = []

    for reason in place.top_reasons:
        signal = _classify_signal(_reason_text(reason), "top_reason")
        signals.append(signal)
        if signal.strength == "direct_fact":
            direct_facts.append(signal.text)
        elif signal.strength == "weak_experience":
            weak_experience.append(signal.text)
        elif signal.strength == "risk_only_warning":
            risk_only_warnings.append(signal.text)
        elif signal.strength == "not_authorized":
            _add_count(not_authorized_reasons, signal.reason)
        else:
            omitted_count += 1

    for warning in place.warnings:
        signal = _classify_signal(_reason_text(warning), "warning")
        signals.append(signal)
        if signal.strength == "risk_only_warning":
            risk_only_warnings.append(signal.text)
        elif signal.strength == "not_authorized":
            _add_count(not_authorized_reasons, signal.reason)
        elif signal.strength == "omitted":
            omitted_count += 1

    payload = PlaceEvidencePayload(
        place_id=place.place_id,
        name=place.name,
        place_type=place.place_type,
        direct_facts=_dedupe_limited(direct_facts),
        weak_experience=_dedupe_limited(weak_experience),
        risk_only_warnings=_dedupe_limited(risk_only_warnings),
        not_authorized_reasons=not_authorized_reasons,
        omitted_count=omitted_count,
        mandatory_mention_policy=(
            mandatory_mention_policy or MandatoryMentionPolicy()
        ),
    )
    return payload, signals


def _route_places(route_plans: list[RoutePlan] | None) -> list[CandidatePlace]:
    if not route_plans:
        return []
    places: list[CandidatePlace] = []
    seen: set[int] = set()
    for route_plan in route_plans:
        for day_group in route_plan.day_groups:
            for place in day_group.places:
                if place.place_id in seen:
                    continue
                places.append(place)
                seen.add(place.place_id)
    return places


def build_deterministic_action_plan(
    route_plans: list[RoutePlan] | None,
    composition_blueprints: list[CompositionBlueprint] | None,
) -> list[DeterministicActionContract]:
    """Build the complete pre-Writer contract by stable route identity."""
    contracts: list[DeterministicActionContract] = []
    for zero_index, route_plan in enumerate(route_plans or []):
        plan_index = zero_index + 1
        blueprint = (
            composition_blueprints[zero_index]
            if (
                composition_blueprints
                and zero_index < len(composition_blueprints)
            )
            else None
        )
        blueprint_stops = {
            (day.day, stop.place_id): (stop.role, stop.meal_slot)
            for day in (blueprint.days if blueprint is not None else [])
            for stop in day.stops
        }
        for day_group in route_plan.day_groups:
            for place in day_group.places:
                role, meal_slot = blueprint_stops.get(
                    (day_group.day, place.place_id),
                    ("", None),
                )
                contracts.append(DeterministicActionContract(
                    plan_index=plan_index,
                    day=day_group.day,
                    place_id=place.place_id,
                    place_name=place.name,
                    blueprint_role=role,
                    meal_slot=meal_slot,
                    authorized_actions=authorized_actions_for_place(
                        place,
                        role,
                        meal_slot,
                    ),
                ))
    return contracts


def missing_action_contract_keys(
    action_plan: list[DeterministicActionContract],
    route_plans: list[RoutePlan],
) -> list[tuple[int, int, int]]:
    """Return non-transfer locked keys that have no usable action contract."""
    by_key = {contract.key: contract for contract in action_plan}
    missing: list[tuple[int, int, int]] = []
    for plan_index, route_plan in enumerate(route_plans, 1):
        for day_group in route_plan.day_groups:
            for place in day_group.places:
                key = (plan_index, day_group.day, place.place_id)
                contract = by_key.get(key)
                if (
                    contract is not None
                    and contract.blueprint_role == "transfer_context"
                ):
                    continue
                if contract is None or not contract.authorized_actions:
                    missing.append(key)
    return missing


def _authorized_actions_for_role(
    role: str,
    meal_slot: str | None,
) -> tuple[str, ...]:
    """Return deterministic, fact-free activity *guidance* for the blueprint role.

    These are writing-direction cues, NOT verbatim sentences to copy.
    They never authorize dishes, prices, opening hours, history, exhibits,
    views, or any other external fact.
    """
    if role == "meal_stop":
        if meal_slot == "lunch":
            # First item stays noun-like: completion_sentence_for_contract
            # renders it as "到{place}后，安排{action}。".
            return (
                "午餐与休整",
                "[INTERNAL 写作指引，勿输出] 这是午餐节点，写出坐下来吃饭、放慢节奏的在场感",
            )
        if meal_slot == "dinner":
            return (
                "晚餐与休整",
                "[INTERNAL 写作指引，勿输出] 这是晚餐节点，写出一天收尾、坐下来好好吃顿饭的状态感",
            )
        return (
            "用餐与休整",
            "[INTERNAL 写作指引，勿输出] 这是用餐节点，写出用餐和休息的自然过渡",
        )
    if role == "snack_stop":
        return (
            "小吃或甜品补给",
            "[INTERNAL 写作指引，勿输出] 轻量补给站，写出随手买点吃的、垫垫肚子的随意感",
        )
    if role in {"coffee_stop", "cafe_stop"}:
        # Keep the first three short items and their order: tests and the
        # predispatch meal normalizer rely on them.
        return (
            "咖啡或茶歇",
            "坐下休息",
            "简单补给",
            "[INTERNAL 写作指引，勿输出] 中场休息站，写出坐下来喝杯东西、歇歇脚的状态，用你自己的表达",
        )
    if role == "optional_stop":
        return (
            "[INTERNAL 写作指引，勿输出] 可选停留，时间宽裕就逛逛，赶时间就略过，写出轻松随意的态度",
        )
    if role == "transfer_context":
        return (
            "作为区域或换乘语境轻写",
            "简写区域之间的换乘衔接",
            "交代抵达后的区域转换",
            "带过换乘节点的衔接语境",
        )
    if role == "photo_stop":
        return (
            "[INTERNAL 写作指引，勿输出] 拍照停留点，写出怎么取景、怎么找角度的具体建议，不要用模板句",
        )
    if role in {"anchor_activity", "anchor"}:
        return (
            "[INTERNAL 写作指引，勿输出] 当天重头戏，分配最多笔墨，写出在场感、节奏感和空间感，让读者能想象自己在这里逛的样子",
        )
    if role in {"secondary_activity", "secondary"}:
        return (
            "[INTERNAL 写作指引，勿输出] 次要停留，不用太长，写出精炼的看点和节奏控制",
        )
    return ()


def _fact_free_activity_actions(
    place_type: str,
    category_tags: list[str] | tuple[str, ...],
) -> tuple[str, ...]:
    """Return writing-direction cues based on place type, not verbatim sentences."""
    normalized_type = (place_type or "").strip().lower()
    tags = " ".join(str(tag or "") for tag in category_tags)

    if normalized_type == "museum" or "博物馆" in tags:
        return (
            "[INTERNAL 写作指引，勿输出] 博物馆/展馆类，写出选展区、看展品、在馆内放慢脚步的节奏感",
        )
    if normalized_type == "park" or "公园" in tags:
        return (
            "[INTERNAL 写作指引，勿输出] 公园类，写出散步、找地方坐下、感受自然和人间气息的松弛感",
        )
    if normalized_type == "market" or any(
        marker in tags for marker in ("市场", "市集", "菜市")
    ):
        return (
            "[INTERNAL 写作指引，勿输出] 市场/市集类，写出沿摊位逛、观察日常生活、随手买点东西的烟火气",
        )
    if normalized_type == "business_area" or any(
        marker in tags for marker in ("商业街", "商圈", "街区漫步")
    ):
        return (
            "[INTERNAL 写作指引，勿输出] 商业街区类，写出沿街逛店、拐进支路发现小店、在街区漫步的闲逛感",
        )
    if normalized_type == "photo_spot" or "拍照" in tags:
        return (
            "[INTERNAL 写作指引，勿输出] 拍照点，写出怎么找角度、怎么取景的具体建议",
        )
    if any(
        marker in tags
        for marker in ("街巷", "老城", "林荫路", "生活感")
    ):
        return (
            "[INTERNAL 写作指引，勿输出] 街巷/老城类，写出在巷子里慢慢走、看门牌窗台旧墙这些细节的沉浸感",
        )
    if any(
        marker in tags
        for marker in ("历史建筑", "历史文化", "寺庙", "文化艺术")
    ):
        return (
            "[INTERNAL 写作指引，勿输出] 历史建筑/文化类，写出绕着建筑看、观察细节做工、感受空间氛围的体验",
        )
    if any(
        marker in tags
        for marker in ("自然风光", "观景", "夜景", "滨江", "湿地")
    ):
        return (
            "[INTERNAL 写作指引，勿输出] 自然观景类，写出找个开阔位置停下来看、沿步道慢走、感受地形和光线变化的体验",
        )
    if normalized_type in {"attraction", "photo_spot"}:
        return (
            "[INTERNAL 写作指引，勿输出] 景点/游览类，写出按自己节奏逛、挑重点看、累了歇歇的自在感",
        )
    return ()


# Last-resort fact-free actions for places outside every role/type/tag
# mapping (June 2026 production examples: type='other' streets, cable cars
# and bookstores with empty category_tags and no blueprint role). Keeps the
# deterministic action contract non-empty so keyed completion and the
# v0.9.4 SafePlanRenderer never starve on an unmapped place. The first item
# must read naturally after "到{place}后，" in
# completion_sentence_for_contract.
_GENERIC_FALLBACK_ACTIONS: tuple[str, ...] = (
    "[INTERNAL 写作指引，勿输出] 通用地点，按自己的节奏看看走走，写出轻松自在的在场感",
)


def authorized_actions_for_place(
    place: CandidatePlace,
    role: str,
    meal_slot: str | None,
) -> tuple[str, ...]:
    """Combine role permissions with type-aware, fact-free activity guidance."""
    base = _authorized_actions_for_role(role, meal_slot)
    if role in {
        "meal_stop",
        "snack_stop",
        "coffee_stop",
        "cafe_stop",
        "transfer_context",
    }:
        return base
    normalized_type = (place.place_type or "").strip().lower()
    meal_type_actions = {
        "restaurant": ("按需用餐与休整",),
        "cafe": ("咖啡或茶歇", "坐下休息"),
        "snack": ("小吃或甜品补给",),
    }.get(normalized_type, ())
    if meal_type_actions:
        # The place type is authoritative for Activity wording even when the
        # composition blueprint classifies an extra food stop as optional.
        # Keep the blueprint role, but put a detector-compatible, fact-free
        # meal action first so keyed local completion cannot insert
        # attraction-like wording for a restaurant/cafe/snack POI.
        return tuple(dict.fromkeys([*meal_type_actions, *base]))
    type_actions = _fact_free_activity_actions(
        place.place_type,
        place.category_tags,
    )
    combined = tuple(dict.fromkeys([*base, *type_actions]))
    if combined:
        return combined
    # Role-miss plus type/tag-miss: never return an empty contract.
    return _GENERIC_FALLBACK_ACTIONS


def _summary_metrics(evidence_summary: str) -> dict[str, Any]:
    counts = {
        "direct_fact": 0,
        "weak_experience": 0,
        "risk_only_warning": 0,
        "not_authorized": 0,
        "omitted": 0,
    }
    reasons: dict[str, int] = {}
    fragments = [
        fragment.strip()
        for fragment in _SUMMARY_SPLIT_RE.split(evidence_summary or "")
        if fragment.strip()
    ]
    for fragment in fragments:
        signal = _classify_signal(fragment, "evidence_summary")
        counts[signal.strength] += 1
        if signal.strength == "not_authorized":
            _add_count(reasons, signal.reason)
    return {
        "evidence_summary_signal_count": len(fragments),
        "evidence_summary_strength_counts": counts,
        "evidence_summary_not_authorized_reasons": sorted(reasons),
    }


def _signal_rule_metrics(signals: list[EvidenceSignal]) -> dict[str, Any]:
    layer_counts: dict[str, int] = {}
    rule_counts: dict[str, int] = {}
    risk_counts: dict[str, int] = {}
    for signal in signals:
        layer_counts[signal.rule_layer] = layer_counts.get(signal.rule_layer, 0) + 1
        if signal.rule_id:
            rule_counts[signal.rule_id] = rule_counts.get(signal.rule_id, 0) + 1
        if signal.risk_level:
            risk_counts[signal.risk_level] = risk_counts.get(signal.risk_level, 0) + 1
    return {
        "rule_layer_counts": dict(sorted(layer_counts.items())),
        "rule_id_counts": dict(sorted(rule_counts.items())),
        "rule_risk_level_counts": dict(sorted(risk_counts.items())),
    }


def build_structured_evidence_payload(
    retrieval: RetrievalResult,
    route_plans: list[RoutePlan] | None = None,
    composition_blueprints: list[CompositionBlueprint] | None = None,
) -> StructuredEvidencePayload:
    """Build a runtime-only authorization payload from raw retrieval evidence."""
    places = _route_places(route_plans) or retrieval.candidates
    action_plan = build_deterministic_action_plan(
        route_plans,
        composition_blueprints,
    )
    payloads: list[PlaceEvidencePayload] = []
    signal_count = 0
    all_signals: list[EvidenceSignal] = []
    for place in places:
        payload, signals = _place_payload(
            place,
        )
        payloads.append(payload)
        signal_count += len(signals)
        all_signals.extend(signals)
    metrics = {
        "source_signal_count": signal_count,
        **_signal_rule_metrics(all_signals),
        **_summary_metrics(retrieval.evidence_summary),
    }
    payload = StructuredEvidencePayload(
        version=PAYLOAD_VERSION,
        places=payloads,
        action_plan=action_plan,
        classifier_fail_closed=True,
        metrics=metrics,
    )
    if route_plans and len(route_plans) == 1:
        return payload.for_route_plan(route_plans[0], plan_index=1)
    return payload


def has_forbidden_evaluation_word(text: str) -> bool:
    return bool(_contains_any(text or "", _FORBIDDEN_EVALUATION_WORDS))


def render_place_evidence_line(place: CandidatePlace, payload: StructuredEvidencePayload) -> str:
    by_id = {item.place_id: item for item in payload.places}
    item = by_id.get(place.place_id)
    if item is None:
        return f"- {place.name}({place.place_type}) | omitted_count=1"
    parts = [f"- {item.name}({item.place_type})"]
    policy = item.mandatory_mention_policy
    if policy.mandatory_mention:
        policy_parts = ["mandatory_mention=true"]
        if policy.blueprint_role:
            policy_parts.append(f"blueprint_role={policy.blueprint_role}")
        if policy.authorized_actions:
            filtered = [
                a for a in policy.authorized_actions
                if not str(a).startswith("[INTERNAL")
            ]
            hints = [
                str(a).replace("[INTERNAL 写作指引，勿输出] ", "")
                for a in policy.authorized_actions
                if str(a).startswith("[INTERNAL")
            ]
            if filtered:
                policy_parts.append(
                    "authorized_actions=" + "/".join(filtered)
                )
            if hints:
                policy_parts.append(
                    "writing_role_hint=" + "/".join(hints)
                )
        if policy.reason:
            policy_parts.append(f"reason={policy.reason}")
        parts.append("mandatory_mention_policy: " + ", ".join(policy_parts))
    if item.direct_facts:
        parts.append("可直接陈述: " + "；".join(item.direct_facts))
    if item.weak_experience:
        parts.append("可弱表达: " + "；".join(item.weak_experience))
    if item.risk_only_warnings:
        parts.append("只能条件提醒: " + "；".join(item.risk_only_warnings))
    if item.not_authorized_reasons:
        parts.append(
            "禁止使用摘要: "
            + "；".join(
                f"{reason}={count}"
                for reason, count in sorted(item.not_authorized_reasons.items())
            )
        )
    if item.omitted_count:
        parts.append(f"omitted_count={item.omitted_count}")
    if len(parts) == 1:
        parts.append("无可写授权证据")
    return " | ".join(parts)


def render_structured_evidence_prompt(
    payload: StructuredEvidencePayload,
    *,
    title: str = "Structured Evidence Payload（runtime-only）",
) -> str:
    lines = [
        f"{title}: version={payload.version}, classifier_fail_closed=true",
        "证据强度规则：direct_facts 可贴近原句复述；weak_experience 只能使用“整体/相对/适合/可以”等弱表达；risk_only_warnings 只能写成条件性风险提醒；not_authorized/omitted 不能写入攻略。",
        "Mandatory Mention Policy：mandatory_mention=true 的地点必须出现在对应 Day 正文、Day 标题和 day_place_names 中；authorized_actions 是后端根据蓝图角色与地点类型给出的写作参考素材，不是必须照抄的句子——你可以用自己的表达替代，只要不编造事实。每个锁定地点至少写一个具体可执行动作；有 direct_facts/weak_experience 时把动作和可写信息结合。仅复述路线、通勤起终点或空壳停留句不算活动内容；动作不能扩成菜品、口味、价格、开放时间、历史年代、具体展品等可核验事实。基于地点类型写这类地方普遍会有的画面（街巷的石阶旧门面、滨江的江面江风、公园的绿意树荫、老厂房的梁柱层高）属于品类常识，不算编造，可以写；但不做可证伪的具体断言。",
        "语言授权：可以/适合必须绑定证据强度、地点类型、路线或蓝图角色；建议/考虑只用于条件或约束；推荐/值得/很好/亮点/必去/宝藏默认禁用。",
    ]
    for place in payload.places:
        fake_place = CandidatePlace(
            place_id=place.place_id,
            name=place.name,
            place_type=place.place_type,
        )
        lines.append(render_place_evidence_line(fake_place, payload))
    return "\n".join(lines)
