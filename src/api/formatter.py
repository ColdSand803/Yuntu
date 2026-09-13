"""Shared response formatter for API consumers."""

from __future__ import annotations

from src.agents.route_notices import (
    MISSING_ALTERNATIVE_NOTICE,
    ROUTE_DEGRADATION_NOTICE,
    SHORTENED_ROUTE_NOTICE,
)
from src.agents.schema import WorkflowResult


def _commute_reference_lines(result: WorkflowResult, plan_index: int) -> list[str]:
    if plan_index >= len(result.route_plans):
        return []
    route_plan = result.route_plans[plan_index]
    if not route_plan.day_groups:
        return []

    lines = []
    plan_text = result.plans[plan_index].plan_text
    for day_group in route_plan.day_groups:
        notes = [
            note
            for note in day_group.commute_notes
            if note and note not in plan_text
        ]
        if notes:
            lines.append(f"- Day {day_group.day}：" + "；".join(notes))
    if not lines:
        return []
    return ["通勤参考：", *lines]


def format_plans_markdown(result: WorkflowResult) -> str:
    """Format WorkflowResult into Markdown text for Hermes to forward."""
    req = result.trip_request
    lines: list[str] = []

    lines.append(f"🗺️ *{req.to_city} {req.days}天* · {req.people_count}人")
    if req.preferences:
        lines.append(f"偏好：{'、'.join(req.preferences)}")
    if req.avoid:
        lines.append(f"避开：{'、'.join(req.avoid)}")
    lines.append("")

    if not result.plans:
        notice = result.review_notes or (
            "暂时没有找到合适的行程数据，请换个描述试试。"
        )
        lines.append(f"⚠️ {notice}")
        return "\n".join(lines)

    for i, plan in enumerate(result.plans, 1):
        lines.append(f"*方案 {i}：{plan.plan_name}*")
        lines.append(plan.plan_text)
        lines.extend(_commute_reference_lines(result, i - 1))
        lines.append("")

    if any(
        route_plan.day_groups
        and len(route_plan.day_groups) < req.days
        for route_plan in result.route_plans
    ):
        lines.append(f"⚠️ {SHORTENED_ROUTE_NOTICE}")

    review_notes = result.review_notes or ""
    if MISSING_ALTERNATIVE_NOTICE in review_notes:
        lines.append(f"⚠️ {MISSING_ALTERNATIVE_NOTICE}")
    if ROUTE_DEGRADATION_NOTICE in review_notes:
        lines.append(f"⚠️ {ROUTE_DEGRADATION_NOTICE}")
    remaining_review_notes = review_notes
    for notice in (
        MISSING_ALTERNATIVE_NOTICE,
        ROUTE_DEGRADATION_NOTICE,
    ):
        remaining_review_notes = remaining_review_notes.replace(
            notice,
            "",
        )
    remaining_review_notes = remaining_review_notes.strip()
    if "未通过" in remaining_review_notes:
        lines.append(f"_📋 {remaining_review_notes[:200]}_")

    return "\n".join(lines)
