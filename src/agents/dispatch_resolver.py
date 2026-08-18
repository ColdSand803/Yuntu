"""Deterministic Dispatch Resolver for v0.8.13 content recovery.

Reuses issue taxonomy for diagnosis only. Review/gate ``publish_action`` is
observation-only and never executed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from src.agents.generation_issues import GenerationIssue

DispatchAction = Literal[
    "INVARIANT_FAILURE",
    "FRAGMENT_REPAIR",
    "PUBLISH_RETRY",
    "RECORD_ONLY",
    "FAIL_CLOSED",
]

ACTION_RANK: dict[DispatchAction, int] = {
    "RECORD_ONLY": 1,
    "FRAGMENT_REPAIR": 2,
    "PUBLISH_RETRY": 3,
    "FAIL_CLOSED": 4,
    "INVARIANT_FAILURE": 5,
}

# O1 structural order/membership findings: never Fragment Repair / whole-plan repair.
STRUCTURAL_ORDER_REASONS = {
    "declared_day_count_mismatch",
    "text_day_count_mismatch",
    "declared_locked_day_group_violation",
    "text_locked_day_group_violation",
    "ambiguous_alias",
    "day_place_names_mismatch",
    "plan_text_missing_locked_stop",
    "cross_day_poi",
    "route_outside_poi",
}

STRUCTURAL_INCOMPLETE_REASONS = {
    "too_short_plan_text",
    "empty_plan_text",
    "structurally_incomplete",
    "missing_day",
    "empty_day",
    "truncated_skeleton",
    "outline_only",
}

INVARIANT_REASONS = {
    "invariant_place_merge",
    "invariant_route_signature",
    "invariant_commute_legs",
    "city_mismatch",
    "plan_count_mismatch",
    "missing_route_plan",
    "budget_infeasible",
    "budget_overrun_without_exception",
    "fragment_registry_invalidated",
    "food_none_tier_violation",
}

FRAGMENT_REPAIR_WHITELIST = {
    "placeholder_wording",
    "unsupported_fact_expansion",
    "food_tier_exceeded",
    "food_source_attribution",
}

FRAGMENT_POST_VALIDATORS = {
    "placeholder_wording": "PLACEHOLDER_PHRASES",
    "unsupported_fact_expansion": "AUTHORIZED_ACTION_TEMPLATE",
    "food_tier_exceeded": "FOOD_STRUCTURAL_AUTHORIZATION",
    "food_source_attribution": "FOOD_SOURCE_ATTRIBUTION",
}

SOFT_COPY_RECORD_ONLY_REASONS = frozenset({
    "activity_content_missing",
    "blueprint_theme_weak_match",
    "database_tone",
    "generic_copy_quality_warn",
    "plan_similarity_warn",
    "weak_evidence_data_gap",
})


@dataclass(frozen=True)
class DispatchBudgets:
    publish_retry_remaining: int = 1
    fragment_repair_remaining: int = 1
    residual_admits_retry: bool = True
    residual_admits_fragment: bool = True
    after_publish_retry: bool = False


@dataclass
class DispatchDecision:
    action: DispatchAction
    reasons: list[str] = field(default_factory=list)
    plan_indexes: list[int] = field(default_factory=list)
    fragment_issue_codes: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    skip_review: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "reasons": list(self.reasons),
            "plan_indexes": list(self.plan_indexes),
            "fragment_issue_codes": list(self.fragment_issue_codes),
            "notes": list(self.notes),
            "skip_review": self.skip_review,
        }


def _issue_reason(issue: Any) -> str:
    if isinstance(issue, GenerationIssue):
        return str(issue.reason or "")
    if isinstance(issue, dict):
        return str(issue.get("reason") or "")
    return str(getattr(issue, "reason", "") or "")


def _issue_plan_index(issue: Any) -> int | None:
    if isinstance(issue, GenerationIssue):
        return issue.plan_index
    if isinstance(issue, dict):
        value = issue.get("plan_index")
        return int(value) if value is not None else None
    value = getattr(issue, "plan_index", None)
    return int(value) if value is not None else None


def _issue_positive_int_field(issue: Any, field_name: str) -> int | None:
    if isinstance(issue, GenerationIssue):
        value = getattr(issue, field_name, None)
    elif isinstance(issue, dict):
        value = issue.get(field_name)
    else:
        value = getattr(issue, field_name, None)
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _issue_category(issue: Any) -> str:
    if isinstance(issue, GenerationIssue):
        return str(issue.category or "")
    if isinstance(issue, dict):
        return str(issue.get("category") or "")
    return str(getattr(issue, "category", "") or "")


def _issue_publish_action(issue: Any) -> str:
    if isinstance(issue, GenerationIssue):
        return str(issue.publish_action or "")
    if isinstance(issue, dict):
        return str(issue.get("publish_action") or "")
    return str(getattr(issue, "publish_action", "") or "")


def _issue_snippet(issue: Any) -> str:
    if isinstance(issue, GenerationIssue):
        return str(issue.snippet or "")
    if isinstance(issue, dict):
        return str(issue.get("snippet") or "")
    return str(getattr(issue, "snippet", "") or "")


def _issue_strictness(issue: Any) -> tuple[int, int]:
    action_rank = {
        "RECORD_ONLY": 1,
        "REPAIR_PLAN": 2,
        "FAIL_CLOSED": 3,
    }
    category_rank = {
        "WARN": 1,
        "REPAIR": 2,
        "BLOCKER": 3,
    }
    return (
        action_rank.get(_issue_publish_action(issue), 0),
        category_rank.get(_issue_category(issue), 0),
    )


def _issue_surface(issue: Any) -> str:
    if isinstance(issue, GenerationIssue):
        return str((issue.metadata or {}).get("surface") or "")
    if isinstance(issue, dict):
        metadata = issue.get("metadata") or {}
        if isinstance(metadata, dict) and metadata.get("surface"):
            return str(metadata.get("surface"))
        return str(issue.get("surface") or "")
    metadata = getattr(issue, "metadata", None) or {}
    if isinstance(metadata, dict):
        return str(metadata.get("surface") or "")
    return str(getattr(issue, "surface", "") or "")


def _issue_metadata(issue: Any) -> dict[str, Any]:
    if isinstance(issue, GenerationIssue):
        metadata = issue.metadata or {}
    elif isinstance(issue, dict):
        metadata = issue.get("metadata") or issue
    else:
        metadata = getattr(issue, "metadata", None) or {}
    return metadata if isinstance(metadata, dict) else {}


def _has_span(issue: Any) -> bool:
    metadata = _issue_metadata(issue)
    return (
        metadata.get("start") is not None
        and metadata.get("end") is not None
        and int(metadata.get("end")) > int(metadata.get("start"))
    )


def _fragment_admissible(issue: Any) -> bool:
    reason = _issue_reason(issue)
    if reason not in FRAGMENT_REPAIR_WHITELIST:
        return False
    if reason not in FRAGMENT_POST_VALIDATORS:
        return False
    surface = _issue_surface(issue) or "narrative_sentence"
    if surface == "narrative_sentence":
        return _has_span(issue)
    if surface != "poi_fragment" or reason != "unsupported_fact_expansion":
        return False
    metadata = _issue_metadata(issue)
    action_key = metadata.get("action_contract_key")
    fragment_sha256 = metadata.get("fragment_sha256")
    return (
        _has_span(issue)
        and metadata.get("review_anchored") is True
        and isinstance(metadata.get("phrase"), str)
        and bool(metadata.get("phrase"))
        and isinstance(fragment_sha256, str)
        and len(fragment_sha256) == 64
        and all(char in "0123456789abcdef" for char in fragment_sha256)
        and isinstance(action_key, dict)
        and action_key.get("plan_index") == _issue_plan_index(issue)
        and action_key.get("day") == _issue_positive_int_field(issue, "day")
        and action_key.get("place_id") == _issue_positive_int_field(
            issue,
            "place_id",
        )
    )


def _pick_stricter(left: DispatchAction, right: DispatchAction) -> DispatchAction:
    return left if ACTION_RANK[left] >= ACTION_RANK[right] else right


def resolve_dispatch(
    *,
    structural_incomplete: list[Any] | None = None,
    structural_order_membership: list[Any] | None = None,
    invariant_findings: list[Any] | None = None,
    preflight_findings: list[Any] | None = None,
    review_issues: list[Any] | None = None,
    budgets: DispatchBudgets | None = None,
) -> DispatchDecision:
    """Map structural + preflight + review findings to one DispatchAction."""
    budgets = budgets or DispatchBudgets()
    incomplete = list(structural_incomplete or [])
    order_membership = list(structural_order_membership or [])
    invariants = list(invariant_findings or [])
    preflight = list(preflight_findings or [])
    reviews = list(review_issues or [])

    notes: list[str] = []
    reasons: list[str] = []
    plan_indexes: set[int] = set()
    fragment_codes: list[str] = []
    action: DispatchAction = "RECORD_ONLY"
    skip_review = False

    def absorb(issue: Any) -> None:
        reason = _issue_reason(issue)
        if reason:
            reasons.append(reason)
        plan_index = _issue_plan_index(issue)
        if plan_index is not None and plan_index >= 1:
            plan_indexes.add(plan_index)

    # 1) Invariants
    if invariants:
        for issue in invariants:
            absorb(issue)
        return DispatchDecision(
            action="INVARIANT_FAILURE",
            reasons=_dedupe(reasons),
            plan_indexes=sorted(plan_indexes),
            notes=["invariant findings dominate"],
            skip_review=True,
        )

    # 2) Incomplete structure → Retry/Fail, no Review
    if incomplete:
        for issue in incomplete:
            absorb(issue)
        if budgets.after_publish_retry or budgets.publish_retry_remaining <= 0:
            action = "FAIL_CLOSED"
            notes.append("incomplete after retry budget exhausted")
        elif not budgets.residual_admits_retry:
            action = "FAIL_CLOSED"
            notes.append("retry_not_admitted_due_to_remaining_budget")
        else:
            action = "PUBLISH_RETRY"
            notes.append("structurally incomplete → publish retry")
        return DispatchDecision(
            action=action,
            reasons=_dedupe(reasons),
            plan_indexes=sorted(plan_indexes),
            notes=notes,
            skip_review=True,
        )

    # 3) Complete + order/membership structural is deterministic fail-closed.
    # A second Writer sample cannot be allowed to renegotiate the locked route.
    if order_membership:
        for issue in order_membership:
            absorb(issue)
        action = "FAIL_CLOSED"
        notes.append("structural order/membership → fail-closed")
        # Review may already have run for complete bodies; do not re-run here.
        return DispatchDecision(
            action=action,
            reasons=_dedupe(reasons),
            plan_indexes=sorted(plan_indexes),
            notes=notes,
            skip_review=False,
        )

    # 4) Content issues from preflight + review (observation taxonomy only)
    # Prefer span-qualified preflight findings over same-reason taxonomy issues
    # without anchors, so whitelist FR remains reachable in the real pipeline.
    preferred: dict[tuple[Any, ...], Any] = {}

    def _pref_key(issue: Any) -> tuple[Any, ...]:
        return (
            _issue_plan_index(issue) or 0,
            _issue_reason(issue),
            _issue_snippet(issue),
        )

    for issue in [*reviews, *preflight]:
        key = _pref_key(issue)
        existing = preferred.get(key)
        if existing is None:
            preferred[key] = issue
            continue
        strict = (
            issue
            if _issue_strictness(issue) > _issue_strictness(existing)
            else existing
        )
        anchored = (
            issue
            if _has_span(issue) and not _has_span(existing)
            else existing
        )
        if (
            strict is not anchored
            and isinstance(strict, GenerationIssue)
            and isinstance(anchored, GenerationIssue)
            and _has_span(anchored)
        ):
            preferred[key] = strict.model_copy(update={
                "day": strict.day or anchored.day,
                "metadata": {
                    **(strict.metadata or {}),
                    **(anchored.metadata or {}),
                },
            })
        else:
            preferred[key] = strict

    candidates = list(preferred.values())

    def _covered_placeholder_wrapper(issue: Any) -> bool:
        if _issue_reason(issue) != "placeholder_wording" or _has_span(issue):
            return False
        snippet = _issue_snippet(issue)
        if not snippet:
            return False
        return any(
            sibling is not issue
            and _issue_reason(sibling) == "placeholder_wording"
            and _issue_plan_index(sibling) == _issue_plan_index(issue)
            and _fragment_admissible(sibling)
            and _issue_snippet(sibling)
            and _issue_snippet(sibling) in snippet
            for sibling in candidates
        )

    # Do not collapse distinct claims merely because they share reason+plan.
    # A soft WARN with a span must never erase a separate hard REPAIR claim.
    # The only broad wrapper we suppress is the old placeholder detector when
    # its exact phrase already has an admissible preflight span.
    combined = [
        issue
        for issue in candidates
        if not _covered_placeholder_wrapper(issue)
    ]
    has_fragment = False
    has_warn_only = False

    for issue in combined:
        reason = _issue_reason(issue)
        category = _issue_category(issue)
        absorb(issue)

        if reason in STRUCTURAL_ORDER_REASONS:
            action = _pick_stricter(action, "FAIL_CLOSED")
            notes.append(f"late structural order reason {reason} → fail-closed")
            continue

        if reason in STRUCTURAL_INCOMPLETE_REASONS:
            # BODY_INCOMPLETE is the only family allowed to consume the one
            # whole-plan retry budget.
            action = _pick_stricter(action, "PUBLISH_RETRY")
            notes.append(f"late body-incomplete reason {reason} → publish retry")
            continue

        if (
            reason in SOFT_COPY_RECORD_ONLY_REASONS
            or _issue_metadata(issue).get("fact_policy") == "soft_prose_shadow"
        ):
            has_warn_only = True
            notes.append(f"soft copy {reason} → record only")
            continue

        if reason in FRAGMENT_REPAIR_WHITELIST:
            if _fragment_admissible(issue):
                has_fragment = True
                fragment_codes.append(reason)
                continue
            # A hard content issue without one stable owner is not repairable.
            # Whole-plan resampling is forbidden for content defects.
            if category in {"BLOCKER", "REPAIR"}:
                action = _pick_stricter(action, "FAIL_CLOSED")
                notes.append(
                    f"whitelist {reason} without stable fragment → fail-closed"
                )
            else:
                has_warn_only = True
                notes.append(f"whitelist {reason} without span warn → record only")
            continue

        if reason == "unsupported_fact_expansion" and category in {"BLOCKER", "REPAIR"}:
            action = _pick_stricter(action, "FAIL_CLOSED")
            notes.append(
                "hard unsupported_fact_expansion without local validator → fail-closed"
            )
            continue

        if category == "WARN" or reason in {
            "generic_copy_quality_warn",
            "weak_evidence_data_gap",
        }:
            has_warn_only = True
            continue

        if reason in {
            "rare_character_compatibility",
            "duplicate_day_heading",
            "commute_prose_violation",
            "transit_detail_in_prose",
            "transit_summary_altered",
            "transit_line_not_allowed",
            "transit_stop_not_allowed",
            "transit_direction_invented",
            "too_short_plan_text",
        }:
            # Pre-dispatch handlers should have cleaned these. A residual is a
            # deterministic contract failure, not permission to resample prose.
            action = _pick_stricter(action, "FAIL_CLOSED")
            notes.append(f"handler residual {reason} → fail-closed")
            continue

        if category in {"BLOCKER", "REPAIR"}:
            action = _pick_stricter(action, "FAIL_CLOSED")
            notes.append(f"blocking content {reason} → fail-closed")

    if has_fragment and action in {"RECORD_ONLY", "FRAGMENT_REPAIR"}:
        if budgets.fragment_repair_remaining <= 0:
            action = "FAIL_CLOSED"
            notes.append("fragment budget exhausted → fail-closed")
        elif not budgets.residual_admits_fragment:
            action = "FAIL_CLOSED"
            notes.append("fragment not admitted by residual budget → fail-closed")
        else:
            action = _pick_stricter(action, "FRAGMENT_REPAIR")
            notes.append("whitelist span issues → fragment repair")

    if action == "RECORD_ONLY" and has_warn_only:
        notes.append("warn-only soft issues → record only")

    if action == "PUBLISH_RETRY":
        if budgets.after_publish_retry or budgets.publish_retry_remaining <= 0:
            action = "FAIL_CLOSED"
            notes.append("publish retry budget exhausted → fail-closed")
        elif not budgets.residual_admits_retry:
            action = "FAIL_CLOSED"
            notes.append("retry_not_admitted_due_to_remaining_budget")

    return DispatchDecision(
        action=action,
        reasons=_dedupe(reasons),
        plan_indexes=sorted(plan_indexes),
        fragment_issue_codes=_dedupe(fragment_codes),
        notes=_dedupe(notes),
        skip_review=skip_review,
    )


def classify_structural_reasons(
    issues: list[Any],
) -> tuple[list[Any], list[Any], list[Any]]:
    """Split issues into invariant / incomplete / order-membership buckets."""
    invariants: list[Any] = []
    incomplete: list[Any] = []
    order_membership: list[Any] = []
    for issue in issues:
        reason = _issue_reason(issue)
        if reason in INVARIANT_REASONS:
            invariants.append(issue)
        elif reason in STRUCTURAL_INCOMPLETE_REASONS:
            incomplete.append(issue)
        elif reason in STRUCTURAL_ORDER_REASONS:
            order_membership.append(issue)
    return invariants, incomplete, order_membership


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
