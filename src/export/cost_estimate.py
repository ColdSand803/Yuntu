"""Shared artifact presentation of the public persisted cost projection."""

from __future__ import annotations

from typing import Any

from src.cost_estimate.public import (
    CostEstimateSummary,
    PublicMoneyRangeCny,
)


CATEGORY_LABELS = {
    "intercity_transport": "往返大交通",
    "accommodation": "住宿",
    "local_transport": "市内交通",
    "admission": "门票",
    "meals": "午晚餐",
}
COMPLETENESS_LABELS = {
    "complete": "完整预估",
    "partial": "已估子集",
    "unavailable": "费用暂不可估算",
}


def validate_artifact_cost_estimate(raw: Any) -> CostEstimateSummary:
    return CostEstimateSummary.model_validate(raw)


def range_text(value: PublicMoneyRangeCny) -> str:
    if value.min_cny == value.max_cny:
        return f"¥{value.min_cny}"
    return f"¥{value.min_cny}–¥{value.max_cny}"


def cost_estimate_lines(raw: Any) -> tuple[str, ...]:
    summary = validate_artifact_cost_estimate(raw)
    lines = [
        f"估算状态：{COMPLETENESS_LABELS[summary.completeness]}",
        f"估算时间：{summary.estimated_at.isoformat().replace('+00:00', 'Z')}",
    ]
    for scenario in summary.scenarios:
        if scenario.total_range is None:
            lines.append(f"{scenario.label}｜费用暂不可估算")
        elif scenario.total_scope == "estimated_subset":
            lines.append(
                f"{scenario.label}｜已估 {range_text(scenario.total_range)}｜部分费用待确认"
            )
        else:
            lines.append(f"{scenario.label}｜预估 {range_text(scenario.total_range)}")
        for category in scenario.categories:
            category_label = CATEGORY_LABELS[category.category]
            if category.range is None:
                lines.append(f"{category_label}：待确认（{category.basis_label}）")
            else:
                lines.append(
                    f"{category_label}：{range_text(category.range)}（{category.basis_label}）"
                )
    if summary.assumptions:
        lines.append("估算假设：" + "；".join(item.label for item in summary.assumptions))
    if summary.exclusions:
        lines.append("未计范围：" + "；".join(item.label for item in summary.exclusions))
    lines.append(summary.notice)
    return tuple(lines)


__all__ = [
    "CATEGORY_LABELS",
    "cost_estimate_lines",
    "range_text",
    "validate_artifact_cost_estimate",
]
