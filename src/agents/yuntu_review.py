"""YunTu Review: verify plans don't fabricate, have sources, flag data gaps."""

from __future__ import annotations

import asyncio
import json
import logging
import re

from src.agents.fact_expression_taxonomy import (
    has_denied_verifiable_hard_fact,
    has_hard_fact_marker,
    has_soft_expression_marker,
    has_soft_unauthorized_expression_marker,
)
from src.agents.evidence_strength import (
    StructuredEvidencePayload,
    build_structured_evidence_payload,
    render_structured_evidence_prompt,
)
from src.agents.food_review import FoodAttachmentAuthMap
from src.agents.poi_alias import build_route_name_policy
from src.agents.poi_fragments import fragment_registry_prompt
from src.agents.llm import chat, llm_call_context
from src.agents.generation_issues import GenerationIssue
from src.agents.route_planning import route_plan_violations
from src.agents.schema import (
    BudgetResult,
    CompositionBlueprint,
    PlanOutput,
    PoiIdentityResult,
    RetrievalResult,
    RoutePlan,
)
from src.agents.text_quality import BANNED_DATABASE_PHRASES, extract_claimed_names
from src.agents.weather_advisory import (
    WeatherAdvisoryPayload,
    render_weather_prompt,
)

logger = logging.getLogger(__name__)

ORDINARY_REVIEW_REQUEST_TIMEOUT_SECONDS = 40.0


class ReviewSafetyError(RuntimeError):
    """Raised when review cannot produce a safe plan for delivery."""

    def __init__(
        self,
        message: str,
        *,
        invalid_output_type: str | None = None,
    ) -> None:
        super().__init__(message)
        if invalid_output_type is None:
            if "不是有效 JSON" in message:
                invalid_output_type = "malformed_json"
            elif "缺少" in message:
                invalid_output_type = "missing_required_field"
            elif "必须是" in message or "类型" in message:
                invalid_output_type = "wrong_field_type"
        self.invalid_output_type = invalid_output_type


SYSTEM_PROMPT = """你是云途旅行规划服务的攻略质量审核助手。
请审核生成的旅行攻略方案，检查是否存在地点编造、无来源事实扩写或路线脱节等问题。

输出合法 JSON：
{
  "issues": [
    {
      "category": "REPAIR",
      "publish_action": "REPAIR_PLAN",
      "reason": "unsupported_fact_expansion",
      "plan_index": 1,
      "day": 1,
      "place_id": 123,
      "names": ["地点名"],
      "snippet": "存在问题的正文片段",
      "evidence": "问题原因说明"
    }
  ],
  "overall_notes": "整体审核意见"
}

审核要点：
1. 事实合规性：检查正文是否捏造未经验证的门票价格、具体营业时间或虚假地点。
2. 路线一致性：确认正文与指定游览顺序保持一致。
3. 餐饮与游览节奏：检查午餐/晚餐时段与主要打卡点的搭配是否合理。
4. 语言质量：识别明显的空话套话或无意义复读。"""


MINUTE_TRANSFER_RE = re.compile(r"(?:预计|约|大约|驾车|打车|步行|通勤)?\s*\d+\s*分钟")


def _locked_route_text(route_plans: list[RoutePlan]) -> str:
    sections = []
    for index, route_plan in enumerate(route_plans, 1):
        days = []
        for day in route_plan.day_groups:
            line = f"Day {day.day}: {', '.join(place.name for place in day.places)}"
            if day.commute_notes:
                line += "\n  可信通勤参考: " + "; ".join(day.commute_notes)
            days.append(line)
        label = (
            "锁定路线"
            if route_plan.optimized
            else "降级后的每日地点集合（仅锁定 Day 和地点集合）"
        )
        sections.append(f"方案{index}{label}:\n" + "\n".join(days))
    return "\n\n".join(sections)


def _food_authorization_text(
    attachment_auth_map: FoodAttachmentAuthMap | None,
) -> str:
    if not attachment_auth_map:
        return "无"
    rows = []
    for key, authorization in sorted(attachment_auth_map.items()):
        rows.append({
            "attachment_key": {
                "plan_index": key[0],
                "day": key[1],
                "anchor_place_id": key[2],
                "meal_slot": key[3],
                "food_place_id": key[4],
            },
            "evidence_tier": authorization.evidence_tier,
            "food_name": authorization.food_name,
            "amap_rating": authorization.amap_rating,
            "amap_avg_price": authorization.amap_avg_price,
            "walk_minutes": authorization.walk_minutes,
            "none_tier_text": authorization.none_tier_text,
            "direct_facts": list(authorization.direct_facts),
            "weak_experience": list(authorization.weak_experience),
        })
    return json.dumps(rows, ensure_ascii=False, sort_keys=True)


def _blueprint_text(blueprints: list[CompositionBlueprint]) -> str:
    sections = []
    for index, blueprint in enumerate(blueprints, 1):
        lines = []
        for day in blueprint.days:
            stop_text = "；".join(
                (
                    f"{stop.name}: role={stop.role}"
                    + (f", meal_slot={stop.meal_slot}" if stop.meal_slot else "")
                    + f", emphasis={stop.emphasis}"
                )
                for stop in day.stops
            )
            commute_text = "；".join(
                (
                    f"{commute.from_place_id}->{commute.to_place_id}: "
                    f"{commute.duration_minutes}min, style={commute.style}, "
                    f"must_mention={commute.must_mention}"
                )
                for commute in day.commutes
            )
            lines.append(
                f"Day {day.day}: theme={day.theme_code}/{day.theme_label}; "
                f"stops=[{stop_text}]; commutes=[{commute_text}]"
            )
        sections.append(
            f"方案{index}行程组合蓝图（{blueprint.plan_label}）:\n"
            + "\n".join(lines)
        )
    return "\n\n".join(sections)


def _day_sections(plan_text: str) -> dict[int, str]:
    heading = re.compile(
        r"(?im)^\s*(?:#{1,6}\s*)?(?:\*\*)?\s*"
        r"(?:Day\s*(\d+)|第\s*(\d+)\s*天)[^\n]*?(?:\*\*)?\s*$"
    )
    matches = list(heading.finditer(plan_text))
    sections: dict[int, str] = {}
    for index, match in enumerate(matches):
        day = int(match.group(1) or match.group(2))
        end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(plan_text)
        )
        sections[day] = plan_text[match.start():end]
    return sections


def _day_heading_text(plan_text: str) -> str:
    heading = re.compile(
        r"(?im)^\s*(?:#{1,6}\s*)?(?:\*\*)?\s*"
        r"(?:Day\s*\d+|第\s*\d+\s*天)[^\n]*?(?:\*\*)?\s*$"
    )
    return "\n".join(match.group(0) for match in heading.finditer(plan_text or ""))


def _extract_day_place_names_with_alias_coverage(
    plan_text: str,
    candidate_names: list[str],
) -> list[list[str]]:
    heading = re.compile(
        r"(?im)^\s*(?:#{1,6}\s*)?(?:\*\*)?\s*"
        r"(?:Day\s*(\d+)|第\s*(\d+)\s*天)[^\n]*?(?:\*\*)?\s*$"
    )
    matches = list(heading.finditer(plan_text))
    if not matches:
        return []
    ordered_names = sorted(set(candidate_names), key=lambda name: (-len(name), name))
    days = []
    for index, match in enumerate(matches):
        end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(plan_text)
        )
        section = plan_text[match.start():end]
        found = [
            name
            for name in ordered_names
            if name in section
        ]
        days.append(found)
    return days


def _has_excessive_minute_narration(text: str) -> bool:
    chunks = [chunk.strip() for chunk in re.split(r"[。！？；;\n]+", text)]
    streak = 0
    for chunk in chunks:
        if MINUTE_TRANSFER_RE.search(chunk):
            streak += 1
            if streak >= 3:
                return True
        elif chunk:
            streak = 0
    return False


def _composition_quality_violations(plans: list[PlanOutput]) -> list[dict]:
    violations = []
    for index, plan in enumerate(plans, 1):
        for phrase in BANNED_DATABASE_PHRASES:
            if phrase in plan.plan_text:
                violations.append({
                    "plan_index": index,
                    "reason": "database_flavored_phrase",
                    "phrase": phrase,
                })
        if _has_excessive_minute_narration(plan.plan_text):
            violations.append({
                "plan_index": index,
                "reason": "excessive_mechanical_commute_narration",
            })

        blueprint = plan.composition_blueprint
        if blueprint is None:
            continue
        sections = _day_sections(plan.plan_text)
        for day in blueprint.days:
            section = sections.get(day.day, "")
            for commute in day.commutes:
                if not commute.must_mention:
                    continue
                duration_text = str(commute.duration_minutes)
                if (
                    duration_text not in section
                    and "稍远" not in section
                    and "较远" not in section
                    and "远距离" not in section
                    and "路程" not in section
                ):
                    violations.append({
                        "plan_index": index,
                        "day": day.day,
                        "reason": "missing_long_transfer_mention",
                        "duration_minutes": commute.duration_minutes,
                    })
    return violations


def _budget_violations(
    budget_results: list[BudgetResult] | None,
) -> list[dict]:
    if not budget_results:
        return []
    violations = []
    for plan_index, budget_result in enumerate(budget_results, 1):
        for day in budget_result.days:
            if day.status == "infeasible":
                violations.append({
                    "plan_index": plan_index,
                    "day": day.day,
                    "reason": "budget_infeasible",
                    "commute_minutes": day.commute_minutes,
                    "budget_minutes": day.budget_minutes,
                })
            elif (
                day.commute_minutes > day.budget_minutes
                and day.status != "relaxed_exception"
            ):
                violations.append({
                    "plan_index": plan_index,
                    "day": day.day,
                    "reason": "budget_overrun_without_exception",
                    "status": day.status,
                    "commute_minutes": day.commute_minutes,
                    "budget_minutes": day.budget_minutes,
                })
    return violations


def _route_outside_candidate_violations(
    plans: list[PlanOutput],
    route_plans: list[RoutePlan],
    retrieval: RetrievalResult,
    poi_identity_results: list[PoiIdentityResult] | None = None,
) -> list[dict]:
    violations = []
    for index, plan in enumerate(plans):
        if index >= len(route_plans):
            continue
        locked_places = [
            place
            for day_group in route_plans[index].day_groups
            for place in day_group.places
        ]
        identity_result = (
            poi_identity_results[index]
            if poi_identity_results and index < len(poi_identity_results)
            else plan.poi_identity_result
        )
        candidate_names = [candidate.name for candidate in retrieval.candidates]
        policy = build_route_name_policy(
            locked_places=locked_places,
            candidate_names=candidate_names,
            identity_result=identity_result,
            city_name=retrieval.city,
        )
        route_names = policy.route_names
        extraction_names = [*candidate_names, *route_names]
        text_names = set(extract_claimed_names(
            plan.plan_text,
            extraction_names,
        ))
        outside_text_names = sorted(text_names & policy.forbidden_text_names)
        heading_names = set(extract_claimed_names(
            _day_heading_text(plan.plan_text),
            extraction_names,
        ))
        outside_heading_names = sorted(heading_names - route_names)
        plan_name_names = set(extract_claimed_names(
            plan.plan_name,
            extraction_names,
        ))
        outside_plan_name_names = sorted(plan_name_names - route_names)
        outside_used_names = sorted(set(plan.used_place_names) - route_names)
        day_place_names = {
            name
            for day_names in plan.day_place_names
            for name in day_names
        }
        outside_day_place_names = sorted(day_place_names - route_names)
        if outside_text_names:
            violations.append({
                "plan_index": index + 1,
                "reason": "text_route_outside_candidate",
                "surface": "plan_text",
                "names": outside_text_names,
            })
        if outside_heading_names:
            violations.append({
                "plan_index": index + 1,
                "reason": "text_route_outside_candidate",
                "surface": "day_heading",
                "names": outside_heading_names,
            })
        if outside_plan_name_names:
            violations.append({
                "plan_index": index + 1,
                "reason": "metadata_route_outside_candidate",
                "surface": "plan_name",
                "names": outside_plan_name_names,
            })
        if outside_used_names:
            violations.append({
                "plan_index": index + 1,
                "reason": "metadata_route_outside_candidate",
                "surface": "used_place_names",
                "names": outside_used_names,
            })
        if outside_day_place_names:
            violations.append({
                "plan_index": index + 1,
                "reason": "metadata_route_outside_candidate",
                "surface": "day_place_names",
                "names": outside_day_place_names,
            })
    return violations


def _parse_review_data(raw: str) -> dict:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            raise ReviewSafetyError(
                "审核结果不是有效 JSON",
                invalid_output_type="malformed_json",
            ) from exc
        try:
            data = json.loads(match.group())
        except json.JSONDecodeError as embedded_exc:
            raise ReviewSafetyError(
                "审核结果不是有效 JSON",
                invalid_output_type="malformed_json",
            ) from embedded_exc
    if not isinstance(data, dict):
        raise ReviewSafetyError(
            "审核结果必须是 JSON 对象",
            invalid_output_type="wrong_field_type",
        )
    return data


SEMANTIC_REASON_WHITELIST = {
    "unsupported_fact_expansion",
    "food_place_written_as_attraction",
    "long_transfer_missing_or_misleading",
    "blueprint_theme_weak_match",
    "weak_evidence_data_gap",
    "generic_copy_quality_warn",
    "plan_similarity_warn",
    "fabricated_city",
    "fabricated_place",
    "severe_fact_misleading",
    "weather_unauthorized_claim",
    "weather_route_drift",
    "weather_poi_bound_claim",
    "weather_disclaimer_leak",
    "weather_format_violation",
    "food_tier_exceeded",
    "food_none_tier_violation",
    "food_source_attribution",
}

SEMANTIC_BLOCKER_REASON_WHITELIST = {
    "fabricated_city",
    "fabricated_place",
    "severe_fact_misleading",
    "food_none_tier_violation",
}

SAFE_GENERALIZED_FOOD_REST_MARKERS = (
    "午饭",
    "午餐",
    "晚饭",
    "晚餐",
    "简餐",
    "喝杯",
    "咖啡",
    "坐坐",
    "歇",
    "休息",
    "餐饮",
    "轻松",
)

SEMANTIC_RECORD_ONLY_REASONS = {
    "blueprint_theme_weak_match",
    "weak_evidence_data_gap",
    "generic_copy_quality_warn",
    "plan_similarity_warn",
}

WEATHER_REPAIR_REASONS = {
    "weather_unauthorized_claim",
    "weather_route_drift",
    "weather_poi_bound_claim",
    "weather_disclaimer_leak",
    "weather_format_violation",
}

def _is_safe_generalized_food_rest_issue(raw_issue: dict) -> bool:
    reason = str(raw_issue.get("reason") or "")
    if reason not in {
        "unsupported_fact_expansion",
        "food_place_written_as_attraction",
    }:
        return False
    snippet = str(raw_issue.get("snippet") or "")
    evidence = str(raw_issue.get("evidence") or "")
    names_text = "".join(
        str(name)
        for name in raw_issue.get("names", [])
        if isinstance(name, str)
    ) if isinstance(raw_issue.get("names", []), list) else ""
    if not snippet:
        return False
    if has_hard_fact_marker(snippet):
        return False
    if not any(marker in snippet for marker in SAFE_GENERALIZED_FOOD_REST_MARKERS):
        return False
    meal_role_complaint = any(
        marker in evidence
        for marker in (
            "meal_slot",
            "午餐描述",
            "晚餐角色",
            "咖啡店",
            "简餐信息",
            "提供午餐",
            "作为午餐地点",
        )
    )
    food_like_name = any(
        marker in names_text
        for marker in ("咖啡", "饭", "餐", "厨", "小吃", "大排档", "冰淇淋")
    )
    return meal_role_complaint or food_like_name


def _is_safe_itinerary_narration_issue(raw_issue: dict) -> bool:
    if str(raw_issue.get("reason") or "") != "unsupported_fact_expansion":
        return False
    snippet = str(raw_issue.get("snippet") or "")
    if not snippet:
        return False
    if has_hard_fact_marker(snippet):
        return False
    if has_soft_unauthorized_expression_marker(snippet):
        return False
    return has_soft_expression_marker(snippet)


def _is_review_overreach_record_only(raw_issue: dict) -> bool:
    if str(raw_issue.get("reason") or "") != "unsupported_fact_expansion":
        return False
    snippet = str(raw_issue.get("snippet") or "")
    evidence = str(raw_issue.get("evidence") or "")
    if has_hard_fact_marker(snippet):
        return False
    return any(
        marker in evidence
        for marker in (
            "可接受",
            "未超出",
            "需要核对",
            "需注意",
            "若作为",
            "如被理解",
            "表达组织问题",
            "事实承接不清",
            "角色信息未展开",
            "主题匹配偏弱",
            "语义覆盖偏弱",
            "覆盖偏弱",
            "信息过少",
            "承接偏弱",
            "弱覆盖风险",
            "弱授权表达风险",
            "中性体验包装",
            "只做了顺序式串联",
            "未体现蓝图",
            "未体现",
            "表达不完整",
            "角色表达不足",
            "缺少对应 Day",
            "无法确认",
            "转场语义弱化",
            "机械重复",
            "过度口语化拼接",
            "未结合该点的授权内容",
            "语义上偏向",
            "角色说明",
            "日内角色描述",
            "路线包装",
            "叙事化",
            "一般性转场拼接",
            "地点覆盖风险",
            "记录但",
            "建议仅作记录",
            "不属于问题",
            "可由锁定路线",
            "可信通勤参考支持",
            "分钟数可由",
            "谨慎",
            "不贴合",
        )
    )


def _has_sufficient_long_transfer_hint(raw_issue: dict) -> bool:
    if str(raw_issue.get("reason") or "") != "long_transfer_missing_or_misleading":
        return False
    snippet = str(raw_issue.get("snippet") or "")
    evidence = str(raw_issue.get("evidence") or "")
    if "已包含" in evidence:
        return True
    if any(
        marker in evidence
        for marker in (
            "不属于问题",
            "可由锁定路线",
            "可信通勤参考支持",
            "分钟数可由",
            "通勤分钟本身可信",
            "可信通勤参考可保留",
        )
    ):
        return True
    distance_warning = any(
        marker in snippet
        for marker in (
            "路程稍远",
            "路程较远",
            "这段稍远",
            "这段较远",
            "稍远",
            "较远",
            "长转场",
        )
    )
    # A qualitative distance warning is copy coverage, not a verifiable route
    # claim. Exact commute mode/time remains owned by the deterministic route
    # lock and Publish Gate; Review must not turn weaker wording into a
    # whole-plan retry. Concrete contradictory route claims still remain
    # repairable because they do not satisfy this qualitative-only branch.
    concrete_transport_claim = (
        bool(re.search(r"\d+\s*分钟", snippet))
        or any(
            marker in snippet
            for marker in (
                "公共交通",
                "公交",
                "地铁",
                "轨道交通",
                "驾车",
                "打车",
                "自驾",
                "步行几分钟",
            )
        )
    )
    misleading_evidence = any(
        marker in evidence
        for marker in (
            "与锁定路线冲突",
            "与可信通勤冲突",
            "时长不一致",
            "方式不一致",
            "分钟数错误",
            "模式错误",
            "虚构",
            "误写",
        )
    )
    missing_only_evidence = any(
        marker in evidence
        for marker in (
            "未明确呈现",
            "未给出",
            "未体现",
            "未说明",
            "缺少",
            "表达偏泛",
            "提示偏弱",
        )
    )
    return (
        (distance_warning or missing_only_evidence)
        and not concrete_transport_claim
        and not misleading_evidence
    )


def _unsupported_fact_complaint_text(raw_issue: dict) -> str:
    """Isolate the Review complaint from authorized context in the snippet."""
    snippet = str(raw_issue.get("snippet") or "")
    evidence = str(raw_issue.get("evidence") or "")
    if "正文" in evidence:
        complaint = evidence.rsplit("正文", 1)[-1].strip()
        if complaint:
            return complaint
    for contrast in ("但", "然而", "不过"):
        if contrast in evidence:
            complaint = evidence.rsplit(contrast, 1)[-1].strip()
            if complaint:
                return complaint
    if "；" in evidence:
        tail = evidence.rsplit("；", 1)[-1].strip()
        if tail:
            return tail
    return snippet


def _is_llm_contract_issue_record_only(raw_issue: dict) -> bool:
    reason = str(raw_issue.get("reason") or "")
    if reason not in {
        "unsupported_fact_expansion",
        "food_place_written_as_attraction",
        "long_transfer_missing_or_misleading",
    }:
        return False
    snippet = str(raw_issue.get("snippet") or "")
    if not snippet:
        return True
    fact_surface = (
        _unsupported_fact_complaint_text(raw_issue)
        if reason == "unsupported_fact_expansion"
        else snippet
    )
    if reason == "unsupported_fact_expansion":
        return not _is_hard_unsupported_fact_issue(raw_issue)
    return not has_hard_fact_marker(fact_surface)


def _is_hard_unsupported_fact_issue(raw_issue: dict) -> bool:
    if str(raw_issue.get("reason") or "") != "unsupported_fact_expansion":
        return False
    return (
        has_hard_fact_marker(_unsupported_fact_complaint_text(raw_issue))
        or has_denied_verifiable_hard_fact(
            str(raw_issue.get("evidence") or "")
        )
    )


def _issue_from_review_payload(raw_issue: dict) -> GenerationIssue | None:
    reason = str(raw_issue.get("reason") or "").strip()
    if reason not in SEMANTIC_REASON_WHITELIST:
        return None
    safe_itinerary_narration = _is_safe_itinerary_narration_issue(raw_issue)
    review_overreach_record_only = _is_review_overreach_record_only(raw_issue)
    llm_contract_record_only = _is_llm_contract_issue_record_only(raw_issue)
    safe_food_rest_gap = _is_safe_generalized_food_rest_issue(raw_issue)
    sufficient_long_transfer = _has_sufficient_long_transfer_hint(raw_issue)
    review_snippet = str(raw_issue.get("snippet") or "")
    hard_unsupported_fact = _is_hard_unsupported_fact_issue(raw_issue)
    soft_unauthorized_expression = (
        reason == "unsupported_fact_expansion"
        and has_soft_unauthorized_expression_marker(review_snippet)
        and not has_hard_fact_marker(review_snippet)
        and not hard_unsupported_fact
    )
    weather_issue = reason in WEATHER_REPAIR_REASONS
    raw_names = raw_issue.get("names", [])
    has_named_anchor = (
        isinstance(raw_names, list)
        and any(isinstance(name, str) and name.strip() for name in raw_names)
    )
    has_snippet_anchor = (
        isinstance(raw_issue.get("plan_index"), int)
        and bool(str(raw_issue.get("snippet") or "").strip())
    )
    has_repair_anchor = (
        isinstance(raw_issue.get("plan_index"), int)
        and (has_snippet_anchor or has_named_anchor)
    )
    anchored_severe_fact = reason == "severe_fact_misleading" and has_repair_anchor
    anchored_unsupported_fact = (
        reason == "unsupported_fact_expansion" and has_snippet_anchor
    )
    unanchored_unsupported_fact = (
        reason == "unsupported_fact_expansion" and not has_snippet_anchor
    )
    category = str(raw_issue.get("category") or "WARN").strip().upper()
    raw_publish_action = str(raw_issue.get("publish_action") or "").strip().upper()
    unanchored_blocker_overreach = (
        unanchored_unsupported_fact
        and (category == "BLOCKER" or raw_publish_action == "FAIL_CLOSED")
    )
    if weather_issue:
        category = "REPAIR"
    elif hard_unsupported_fact:
        category = "REPAIR"
    elif soft_unauthorized_expression:
        category = "WARN"
    elif safe_itinerary_narration or review_overreach_record_only or llm_contract_record_only:
        category = "WARN"
    elif unanchored_blocker_overreach:
        category = "REPAIR"
    elif unanchored_unsupported_fact:
        category = "WARN"
    elif safe_food_rest_gap:
        category = "REPAIR"
    elif anchored_severe_fact or anchored_unsupported_fact:
        category = "REPAIR"
    elif sufficient_long_transfer:
        category = "WARN"
    elif reason in SEMANTIC_RECORD_ONLY_REASONS:
        category = "WARN"
    downgraded_blocker = False
    if category == "BLOCKER" and reason not in SEMANTIC_BLOCKER_REASON_WHITELIST:
        category = "REPAIR"
        downgraded_blocker = True
    if category not in {"BLOCKER", "REPAIR", "WARN"}:
        category = "WARN"
    publish_action = str(
        raw_publish_action or (
            "REPAIR_PLAN" if category in {"BLOCKER", "REPAIR"} else "RECORD_ONLY"
        )
    ).strip().upper()
    if weather_issue:
        publish_action = "REPAIR_PLAN"
    elif hard_unsupported_fact:
        publish_action = "REPAIR_PLAN"
    elif soft_unauthorized_expression:
        publish_action = "RECORD_ONLY"
    elif safe_itinerary_narration or review_overreach_record_only or llm_contract_record_only:
        publish_action = "RECORD_ONLY"
    elif unanchored_blocker_overreach:
        publish_action = "REPAIR_PLAN"
    elif unanchored_unsupported_fact:
        publish_action = "RECORD_ONLY"
    elif safe_food_rest_gap:
        publish_action = "REPAIR_PLAN"
    elif anchored_severe_fact or anchored_unsupported_fact:
        publish_action = "REPAIR_PLAN"
    elif sufficient_long_transfer:
        publish_action = "RECORD_ONLY"
    elif reason in SEMANTIC_RECORD_ONLY_REASONS:
        publish_action = "RECORD_ONLY"
    if publish_action not in {"FAIL_CLOSED", "REPAIR_PLAN", "RECORD_ONLY"}:
        publish_action = "REPAIR_PLAN" if category in {"BLOCKER", "REPAIR"} else "RECORD_ONLY"
    if downgraded_blocker and publish_action == "FAIL_CLOSED":
        publish_action = "REPAIR_PLAN"
    if (
        category == "BLOCKER"
        and reason in SEMANTIC_BLOCKER_REASON_WHITELIST
        and not anchored_severe_fact
    ):
        publish_action = "FAIL_CLOSED"
    tags = [
        tag
        for tag in raw_issue.get("tags", [])
        if tag == "DATA_GAP"
    ] if isinstance(raw_issue.get("tags", []), list) else []
    if safe_food_rest_gap and "DATA_GAP" not in tags:
        tags.append("DATA_GAP")
    side_effects = [
        effect
        for effect in raw_issue.get("side_effects", [])
        if effect == "DATA_BACKLOG"
    ] if isinstance(raw_issue.get("side_effects", []), list) else []
    if safe_food_rest_gap and "DATA_BACKLOG" not in side_effects:
        side_effects.append("DATA_BACKLOG")
    names = [
        str(name)
        for name in raw_issue.get("names", [])
        if isinstance(name, str) and name.strip()
    ] if isinstance(raw_issue.get("names", []), list) else []
    metadata = {}
    if reason == "unsupported_fact_expansion":
        metadata["fact_policy"] = (
            "verifiable_hard_fact"
            if hard_unsupported_fact
            else "soft_prose_shadow"
        )
    return GenerationIssue(
        source="llm_review",
        category=category,  # type: ignore[arg-type]
        publish_action=publish_action,  # type: ignore[arg-type]
        reason=reason,
        plan_index=raw_issue.get("plan_index")
        if isinstance(raw_issue.get("plan_index"), int)
        else None,
        day=raw_issue.get("day") if isinstance(raw_issue.get("day"), int) else None,
        place_id=(
            raw_issue.get("place_id")
            if (
                isinstance(raw_issue.get("place_id"), int)
                and not isinstance(raw_issue.get("place_id"), bool)
                and raw_issue.get("place_id") > 0
            )
            else None
        ),
        names=names,
        snippet=str(raw_issue.get("snippet") or ""),
        evidence=str(raw_issue.get("evidence") or ""),
        tags=tags,  # type: ignore[arg-type]
        side_effects=side_effects,  # type: ignore[arg-type]
        metadata=metadata,
    )


def _parse_semantic_issues(raw: str) -> tuple[list[GenerationIssue], str]:
    data = _parse_review_data(raw)
    if "issues" not in data:
        raise ReviewSafetyError(
            "审核结果缺少 issues",
            invalid_output_type="missing_required_field",
        )
    raw_issues = data.get("issues", [])
    if not isinstance(raw_issues, list):
        raise ReviewSafetyError(
            "审核结果 issues 必须是数组",
            invalid_output_type="wrong_field_type",
        )
    issues = []
    for issue_index, raw_issue in enumerate(raw_issues):
        if not isinstance(raw_issue, dict):
            raise ReviewSafetyError(
                f"审核结果 issues[{issue_index}] 必须是 JSON 对象",
                invalid_output_type="wrong_field_type",
            )
        required_fields = ("category", "publish_action", "reason")
        missing_fields = [
            field
            for field in required_fields
            if field not in raw_issue
        ]
        if missing_fields:
            raise ReviewSafetyError(
                "审核结果 issue 缺少必填字段: " + ", ".join(missing_fields),
                invalid_output_type="missing_required_field",
            )
        wrong_type_fields = [
            field
            for field in required_fields
            if not isinstance(raw_issue[field], str)
        ]
        if wrong_type_fields:
            raise ReviewSafetyError(
                "审核结果 issue 字段类型错误: " + ", ".join(wrong_type_fields),
                invalid_output_type="wrong_field_type",
            )
        if any(not raw_issue[field].strip() for field in required_fields):
            raise ReviewSafetyError(
                "审核结果 issue 必填字段不符合 Schema",
                invalid_output_type="schema_validation_failed",
            )
        if raw_issue["category"].strip().upper() not in {
            "BLOCKER", "REPAIR", "WARN",
        }:
            raise ReviewSafetyError(
                "审核结果 issue category 不符合 Schema",
                invalid_output_type="schema_validation_failed",
            )
        if raw_issue["publish_action"].strip().upper() not in {
            "FAIL_CLOSED", "REPAIR_PLAN", "RECORD_ONLY",
        }:
            raise ReviewSafetyError(
                "审核结果 issue publish_action 不符合 Schema",
                invalid_output_type="schema_validation_failed",
            )
        if raw_issue["reason"].strip() not in SEMANTIC_REASON_WHITELIST:
            raise ReviewSafetyError(
                "审核结果 issue reason 不符合 Schema",
                invalid_output_type="schema_validation_failed",
            )
        for field in ("plan_index", "day", "place_id"):
            value = raw_issue.get(field)
            if value is not None and (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value <= 0
            ):
                raise ReviewSafetyError(
                    f"审核结果 issue {field} 类型错误",
                    invalid_output_type="wrong_field_type",
                )
        for field in ("names", "tags", "side_effects"):
            value = raw_issue.get(field)
            if value is not None and (
                not isinstance(value, list)
                or any(not isinstance(item, str) for item in value)
            ):
                raise ReviewSafetyError(
                    f"审核结果 issue {field} 类型错误",
                    invalid_output_type="wrong_field_type",
                )
        for field in ("snippet", "evidence"):
            value = raw_issue.get(field)
            if value is not None and not isinstance(value, str):
                raise ReviewSafetyError(
                    f"审核结果 issue {field} 类型错误",
                    invalid_output_type="wrong_field_type",
                )
        issue = _issue_from_review_payload(raw_issue)
        if issue is None:
            raise ReviewSafetyError(
                "审核结果 issue 未通过 Schema 校验",
                invalid_output_type="schema_validation_failed",
            )
        issues.append(issue)
    overall_notes = data.get("overall_notes", "")
    if not isinstance(overall_notes, str):
        raise ReviewSafetyError(
            "审核结果 overall_notes 类型错误",
            invalid_output_type="wrong_field_type",
        )
    return issues, overall_notes


async def check(
    plans: list[PlanOutput],
    retrieval: RetrievalResult,
    route_plans: list[RoutePlan] | None = None,
    poi_identity_results: list[PoiIdentityResult] | None = None,
    budget_results: list[BudgetResult] | None = None,
) -> tuple[list[PlanOutput], str]:
    """Backward-compatible wrapper around semantic issue collection."""
    if route_plans:
        detected_violations = route_plan_violations(plans, route_plans)
        detected_violations.extend(
            _route_outside_candidate_violations(
                plans,
                route_plans,
                retrieval,
                poi_identity_results,
            )
        )
        detected_violations.extend(_budget_violations(budget_results))
        if detected_violations:
            raise ReviewSafetyError(
                "攻略违反锁定路线: "
                + json.dumps(detected_violations, ensure_ascii=False)
            )
    quality_violations = _composition_quality_violations(plans)
    if quality_violations:
        raise ReviewSafetyError(
            "攻略存在行程组合质量问题: "
            + json.dumps(quality_violations, ensure_ascii=False)
        )
    issues, notes = await collect_semantic_generation_issues(
        plans,
        retrieval,
        route_plans=route_plans,
        composition_blueprints=[
            plan.composition_blueprint
            for plan in plans
            if plan.composition_blueprint is not None
        ] or None,
        return_notes=True,
    )
    if any(issue.category == "BLOCKER" for issue in issues):
        raise ReviewSafetyError(
            "语义审核发现不可发布问题: "
            + json.dumps(
                [issue.model_dump(mode="json") for issue in issues],
                ensure_ascii=False,
            )
        )
    return plans, notes


async def collect_semantic_generation_issues(
    plans: list[PlanOutput],
    retrieval: RetrievalResult,
    route_plans: list[RoutePlan] | None = None,
    composition_blueprints: list[CompositionBlueprint] | None = None,
    *,
    return_notes: bool = False,
    structured_evidence_payload: StructuredEvidencePayload | None = None,
    weather_advisory_payload: WeatherAdvisoryPayload | None = None,
    attachment_auth_map: FoodAttachmentAuthMap | None = None,
    call_reason_prefix: str = "review_taxonomy",
    action_plan_index: int | None = None,
) -> list[GenerationIssue] | tuple[list[GenerationIssue], str]:
    """Collect semantic generation issues without rewriting plan text."""
    payload = structured_evidence_payload or build_structured_evidence_payload(
        retrieval,
        route_plans=route_plans,
        composition_blueprints=composition_blueprints,
    )
    if route_plans and len(route_plans) == 1:
        payload = payload.for_route_plan(
            route_plans[0],
            plan_index=action_plan_index,
        )

    plans_text = []
    for i, p in enumerate(plans, 1):
        fragment_registry = fragment_registry_prompt(p)
        plans_text.append(
            f"方案{i}: {p.plan_name}\n"
            f"使用地点: {', '.join(p.used_place_names)}\n"
            + (
                "后端 keyed POI fragment registry（issue 必须回传这里的 key）：\n"
                f"{fragment_registry}\n"
                if fragment_registry
                else ""
            )
            + f"攻略内容:\n{p.plan_text}"
        )

    user_prompt = (
        "Structured Evidence Payload（攻略中的描述只能基于以下授权内容；"
        "not_authorized/omitted 不能写入正文）：\n"
        + render_structured_evidence_prompt(payload)
        + "\n\n"
        + render_weather_prompt(weather_advisory_payload)
        + "\n\nFood Attachment Authorization（runtime-only；food span 的唯一授权）：\n"
        + _food_authorization_text(attachment_auth_map)
        + "\n\n生成的攻略方案：\n"
        + "\n\n---\n\n".join(plans_text)
    )
    if route_plans:
        user_prompt += (
            "\n\n以下是不可跨 Day 更改的每日地点集合，请检查攻略是否完全遵守：\n"
            + _locked_route_text(route_plans)
            + "\n其中“可信通勤参考”来自确定性路线计算，即使候选地点证据中"
            "没有对应分钟数，也不属于编造事实。"
        )
        if any(not route_plan.optimized for route_plan in route_plans):
            user_prompt += (
                "\n\n注意：optimized=false 的方案是行政区数据不可用时的降级分组。"
                "只检查 Day 数和每个 Day 的地点集合，不检查行政区、通勤距离、"
                "天内地点顺序或白天/夜间优化。天内顺序不同不属于违规。"
            )

    blueprints = composition_blueprints or [
        plan.composition_blueprint
        for plan in plans
        if plan.composition_blueprint is not None
    ]
    if blueprints:
        user_prompt += (
            "\n\n以下是行程组合蓝图，请检查攻略是否遵守：\n"
            + _blueprint_text(blueprints)
            + "\n请重点检查：每天是否有主题导语；餐饮点是否按 meal_slot 写成"
            "午餐/晚餐/小吃/咖啡/可选夜宵；短通勤是否避免机械堆叠；"
            "long_transfer/remote_transfer 是否被明确提示；是否出现数据库口吻。"
        )
        detected_quality = _composition_quality_violations(plans)
        if detected_quality:
            user_prompt += (
                "\n\n确定性校验已发现以下行程组合质量违规：\n"
                + json.dumps(detected_quality, ensure_ascii=False)
                + "\n这些问题请按 issue taxonomy 归类，不要输出修正文案。"
            )

    review_prompt = user_prompt
    last_error: ReviewSafetyError | None = None
    for attempt in range(2):
        with llm_call_context(
            call_reason=f"{call_reason_prefix}_attempt_{attempt + 1}",
            attempt=attempt + 1,
            role="review",
            stage="REVIEW_TAXONOMY",
            max_tokens_request=1200,
            relay_request_timeout_seconds=ORDINARY_REVIEW_REQUEST_TIMEOUT_SECONDS,
            relay_hedge_delay_seconds=1,
        ):
            raw = await chat(
                system=SYSTEM_PROMPT,
                user=review_prompt,
                role="review",
                temperature=0.1,
                json_mode=True,
            )
        logger.info(
            "YunTu Review raw output length: %d attempt=%d",
            len(raw),
            attempt + 1,
        )

        try:
            issues, overall_notes = _parse_semantic_issues(raw)
        except ReviewSafetyError as exc:
            last_error = exc
            if attempt == 1:
                logger.error("YunTu Review taxonomy collection failed: %s", exc)
                raise ReviewSafetyError(
                    f"{last_error or exc}，拒绝返回未经完整语义审核的攻略",
                    invalid_output_type=exc.invalid_output_type,
                ) from exc
            logger.warning(
                "YunTu Review retrying after taxonomy parse failure: %s",
                exc,
            )
            review_prompt = (
                user_prompt
                + "\n\n上一次审核输出不是合法 issue taxonomy JSON。"
                "请重新输出一个完整 JSON 对象，只能包含 issues 和 overall_notes，"
                "不要输出 corrected_plan_text 或任何修正文案。"
            )
            continue

        if len(retrieval.candidates) < 5:
            overall_notes += "\n[数据不足提醒] 当前城市候选地点不足5个，攻略仅供参考。"
        if return_notes:
            return issues, overall_notes
        return issues

    raise last_error or ReviewSafetyError("审核失败")


async def collect_semantic_generation_issues_by_plan(
    plans: list[PlanOutput],
    retrieval: RetrievalResult,
    route_plans: list[RoutePlan] | None = None,
    composition_blueprints: list[CompositionBlueprint] | None = None,
    structured_evidence_payload: StructuredEvidencePayload | None = None,
    weather_advisory_payload: WeatherAdvisoryPayload | None = None,
    attachment_auth_map: FoodAttachmentAuthMap | None = None,
) -> tuple[list[GenerationIssue], dict]:
    """Collect plan-local semantic issues concurrently with the existing schema."""
    if not plans:
        return [], {
            "review_plan_concurrency_used": False,
            "review_plan_latencies_ms": [],
            "review_global_issue_count": 0,
        }

    async def collect_one(zero_index: int, plan: PlanOutput):
        import time

        t0 = time.monotonic()
        single_route_plans = (
            [route_plans[zero_index]]
            if route_plans and zero_index < len(route_plans)
            else None
        )
        single_blueprints = (
            [composition_blueprints[zero_index]]
            if composition_blueprints and zero_index < len(composition_blueprints)
            else None
        )
        issues = await collect_semantic_generation_issues(
            [plan],
            retrieval,
            route_plans=single_route_plans,
            composition_blueprints=single_blueprints,
            structured_evidence_payload=structured_evidence_payload,
            weather_advisory_payload=weather_advisory_payload,
            attachment_auth_map={
                key: authorization
                for key, authorization in (attachment_auth_map or {}).items()
                if key[0] == zero_index
            },
            call_reason_prefix=f"review_taxonomy_plan_{zero_index + 1}",
            action_plan_index=zero_index + 1,
        )
        assert isinstance(issues, list)
        plan_index = zero_index + 1
        remapped = [
            issue.model_copy(update={
                "plan_index": (
                    plan_index
                    if issue.plan_index in (None, 1)
                    else issue.plan_index
                )
            })
            for issue in issues
        ]
        return remapped, int((time.monotonic() - t0) * 1000)

    import time

    t0 = time.monotonic()
    results = await asyncio.gather(*[
        collect_one(zero_index, plan)
        for zero_index, plan in enumerate(plans)
    ])
    all_issues: list[GenerationIssue] = []
    latencies: list[int] = []
    for issues, latency_ms in results:
        all_issues.extend(issues)
        latencies.append(latency_ms)
    return all_issues, {
        "review_plan_concurrency_used": True,
        "review_plan_latencies_ms": latencies,
        "review_parallel_wall_latency_ms": int((time.monotonic() - t0) * 1000),
        "review_global_issue_count": 0,
    }
