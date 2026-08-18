"""Stable-key helpers for backend-owned POI narrative fragments."""

from __future__ import annotations

from difflib import SequenceMatcher

from src.agents.schema import PlanOutput, PoiNarrativeFragment


def fragment_registry_is_intact(plan: PlanOutput) -> bool:
    """Return whether every stable key still owns its exact registered span."""
    text = plan.plan_text or ""
    seen_keys: set[tuple[int, int, int]] = set()
    previous_end = 0
    for fragment in sorted(plan.poi_fragments, key=lambda item: item.start):
        key = (fragment.plan_index, fragment.day, fragment.place_id)
        if (
            key in seen_keys
            or fragment.start < previous_end
            or fragment.end <= fragment.start
            or fragment.end > len(text)
            or text[fragment.start:fragment.end] != fragment.text
        ):
            return False
        seen_keys.add(key)
        previous_end = fragment.end
    return True


def remap_fragment_registry(
    plan: PlanOutput,
    *,
    updated_text: str,
) -> PlanOutput | None:
    """Apply a whole-text deterministic edit without losing stable ownership.

    The mapping is derived from exact old/new offsets, never from place-name or
    finding-text ownership guesses. Edits that cross a fragment boundary are
    rejected because their owner is ambiguous.
    """
    old_text = plan.plan_text or ""
    if not plan.poi_fragments:
        return plan.model_copy(update={"plan_text": updated_text})
    if not fragment_registry_is_intact(plan):
        return None
    if updated_text == old_text:
        return plan

    opcodes = SequenceMatcher(
        None,
        old_text,
        updated_text,
        autojunk=False,
    ).get_opcodes()

    def mapped_boundary(position: int, *, start_boundary: bool) -> int | None:
        for tag, old_start, old_end, new_start, new_end in opcodes:
            if tag == "insert":
                if position == old_start:
                    # Text inserted at a fragment start belongs before it;
                    # text inserted at a fragment end belongs after it.
                    return new_end if start_boundary else new_start
                continue
            if old_start <= position <= old_end:
                if tag == "equal":
                    return new_start + (position - old_start)
                if position == old_start:
                    return new_start
                if position == old_end:
                    return new_end
                return None
        if position == len(old_text):
            return len(updated_text)
        return None

    updated_fragments: list[PoiNarrativeFragment] = []
    for fragment in sorted(plan.poi_fragments, key=lambda item: item.start):
        for tag, old_start, old_end, _new_start, _new_end in opcodes:
            if tag == "equal" or old_start == old_end:
                continue
            if (
                old_start < fragment.start < old_end
                or old_start < fragment.end < old_end
            ):
                return None
        new_start = mapped_boundary(fragment.start, start_boundary=True)
        new_end = mapped_boundary(fragment.end, start_boundary=False)
        if (
            new_start is None
            or new_end is None
            or new_end <= new_start
            or new_end > len(updated_text)
        ):
            return None
        updated_fragments.append(fragment.model_copy(update={
            "text": updated_text[new_start:new_end],
            "start": new_start,
            "end": new_end,
        }))

    updated_plan = plan.model_copy(update={
        "plan_text": updated_text,
        "poi_fragments": updated_fragments,
    })
    return updated_plan if fragment_registry_is_intact(updated_plan) else None


def fragment_for_span(
    plan: PlanOutput,
    *,
    start: int,
    end: int,
) -> PoiNarrativeFragment | None:
    """Resolve a text span only through the backend fragment registry."""
    if start < 0 or end <= start:
        return None
    matches = [
        fragment
        for fragment in plan.poi_fragments
        if fragment.start <= start and end <= fragment.end
    ]
    return matches[0] if len(matches) == 1 else None


def replace_fragment_text(
    plan: PlanOutput,
    *,
    plan_index: int,
    day: int,
    place_id: int,
    replacement: str,
    source: str = "deterministic_completion",
) -> PlanOutput | None:
    """Replace one keyed fragment and shift later immutable spans.

    Ownership is selected solely by ``(plan_index, day, place_id)``.  Text is
    used only as an integrity check after the key has selected the fragment.
    """
    target = plan.poi_fragment(
        plan_index=plan_index,
        day=day,
        place_id=place_id,
    )
    text = plan.plan_text or ""
    replacement = (replacement or "").strip()
    if (
        target is None
        or not replacement
        or target.start < 0
        or target.end <= target.start
        or target.end > len(text)
        or text[target.start:target.end] != target.text
    ):
        return None

    updated_text = text[:target.start] + replacement + text[target.end:]
    delta = len(replacement) - (target.end - target.start)
    updated_fragments: list[PoiNarrativeFragment] = []
    for fragment in plan.poi_fragments:
        if fragment is target:
            updated_fragments.append(fragment.model_copy(update={
                "text": replacement,
                "end": target.start + len(replacement),
                "source": source,
            }))
            continue
        if fragment.start >= target.end:
            updated_fragments.append(fragment.model_copy(update={
                "start": fragment.start + delta,
                "end": fragment.end + delta,
            }))
            continue
        updated_fragments.append(fragment)

    return plan.model_copy(update={
        "plan_text": updated_text,
        "poi_fragments": updated_fragments,
    })


def replace_fragment_range(
    plan: PlanOutput,
    *,
    start: int,
    end: int,
    replacement: str,
) -> PlanOutput | None:
    """Replace a verified subrange while preserving its existing stable key."""
    text = plan.plan_text or ""
    replacement = (replacement or "").strip()
    owner = fragment_for_span(plan, start=start, end=end)
    if (
        owner is None
        or not replacement
        or end > len(text)
        or text[owner.start:owner.end] != owner.text
    ):
        return None

    updated_text = text[:start] + replacement + text[end:]
    delta = len(replacement) - (end - start)
    local_start = start - owner.start
    local_end = end - owner.start
    owner_text = owner.text[:local_start] + replacement + owner.text[local_end:]
    updated_fragments: list[PoiNarrativeFragment] = []
    for fragment in plan.poi_fragments:
        if fragment is owner:
            updated_fragments.append(fragment.model_copy(update={
                "text": owner_text,
                "end": fragment.end + delta,
                "source": "fragment_repair",
            }))
            continue
        if fragment.start >= end:
            updated_fragments.append(fragment.model_copy(update={
                "start": fragment.start + delta,
                "end": fragment.end + delta,
            }))
            continue
        updated_fragments.append(fragment)
    return plan.model_copy(update={
        "plan_text": updated_text,
        "poi_fragments": updated_fragments,
    })


def fragment_registry_prompt(plan: PlanOutput) -> str:
    """Render Review-visible keys without exposing them in the public API."""
    return "\n".join(
        (
            f"- key=({fragment.plan_index},{fragment.day},{fragment.place_id}); "
            f"text={fragment.text}"
        )
        for fragment in plan.poi_fragments
    )
