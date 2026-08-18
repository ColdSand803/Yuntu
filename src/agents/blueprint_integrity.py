"""Deterministic blueprint and locked-stop integrity checks after repair."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.agents.schema import PlanOutput, RoutePlan


@dataclass
class BlueprintViolation:
    plan_index: int
    day: int
    reason: str
    missing_stops: list[str] = field(default_factory=list)
    extra_stops: list[str] = field(default_factory=list)


def check_plan_blueprint_integrity(
    plans: list[PlanOutput],
    route_plans: list[RoutePlan],
    composition_blueprints: list | None = None,
) -> list[BlueprintViolation]:
    """Check declared Day stops and visible Day text against locked routes.

    Declared ``day_place_names`` must ordered-equal final
    ``RouteDayGroup.places`` names (not set membership alone).
    """
    del composition_blueprints
    violations: list[BlueprintViolation] = []
    for plan_idx, plan in enumerate(plans):
        if plan_idx >= len(route_plans):
            continue
        route_plan = route_plans[plan_idx]
        declared = plan.day_place_names or []
        day_sections = _day_sections(plan.plan_text or "")
        for day_idx, day_group in enumerate(route_plan.day_groups):
            day_number = day_group.day or day_idx + 1
            expected_names = [place.name for place in day_group.places if place.name]
            actual_names = (
                list(declared[day_idx])
                if day_idx < len(declared)
                else []
            )
            if actual_names != expected_names:
                expected_set = set(expected_names)
                actual_set = set(actual_names)
                missing = sorted(expected_set - actual_set)
                extra = sorted(actual_set - expected_set)
                # Ordered mismatch with identical membership still fails.
                if not missing and not extra and actual_names:
                    missing = list(expected_names)
                    extra = list(actual_names)
                violations.append(BlueprintViolation(
                    plan_index=plan_idx + 1,
                    day=day_number,
                    reason="day_place_names_mismatch",
                    missing_stops=missing,
                    extra_stops=extra,
                ))

            day_text = day_sections.get(day_number, "")
            text_missing = sorted(
                name for name in expected_names
                if name not in day_text
            )
            if text_missing:
                violations.append(BlueprintViolation(
                    plan_index=plan_idx + 1,
                    day=day_number,
                    reason="plan_text_missing_locked_stop",
                    missing_stops=text_missing,
                ))
    return violations


def normalize_declared_locked_stops(
    plan: PlanOutput,
    route_plan: RoutePlan,
    violations: list[BlueprintViolation],
) -> bool:
    """Normalize metadata only; never synthesize user-visible prose."""
    for violation in violations:
        if violation.reason != "day_place_names_mismatch":
            return False
        if violation.extra_stops:
            return False

    normalized_day_names = [
        [place.name for place in day_group.places if place.name]
        for day_group in route_plan.day_groups
    ]
    plan.day_place_names = normalized_day_names
    plan.used_place_names = list(dict.fromkeys(
        name for day_names in normalized_day_names for name in day_names
    ))
    plan.used_place_ids = list(dict.fromkeys(
        place.place_id
        for day_group in route_plan.day_groups
        for place in day_group.places
    ))
    return True


def _day_sections(plan_text: str) -> dict[int, str]:
    heading = re.compile(
        r"(?im)^\s*(?:#{1,6}\s*)?(?:\*\*)?\s*"
        r"(?:Day\s*(\d+)|第\s*(\d+|[一二三四五六七八九十]+)\s*天)[^\n]*?(?:\*\*)?\s*$"
    )
    matches = list(heading.finditer(plan_text or ""))
    sections: dict[int, str] = {}
    for index, match in enumerate(matches):
        day = _parse_day_heading_number(match.group(1) or match.group(2))
        if day is None:
            continue
        end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(plan_text)
        )
        chunk = plan_text[match.start():end]
        if day in sections:
            # Same-day later headings must not drop earlier body text used for
            # membership visibility checks (duplicate/pseudo headings).
            sections[day] = sections[day].rstrip() + "\n" + chunk.lstrip()
        else:
            sections[day] = chunk
    return sections


def _parse_day_heading_number(value: str | None) -> int | None:
    if not value:
        return None
    if value.isdigit():
        return int(value)
    digits = {
        "一": 1,
        "二": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    if value == "十":
        return 10
    if value.startswith("十") and len(value) == 2:
        tail = digits.get(value[1:])
        return 10 + tail if tail is not None else None
    if value.endswith("十") and len(value) == 2:
        head = digits.get(value[:1])
        return head * 10 if head is not None else None
    if "十" in value and len(value) == 3:
        head = digits.get(value[:1])
        tail = digits.get(value[-1:])
        if head is not None and tail is not None:
            return head * 10 + tail
    return digits.get(value)
