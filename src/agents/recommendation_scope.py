"""Deterministic policy for user-visible recommendation count."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from src.agents.schema import TripRequest


@dataclass(frozen=True)
class RecommendationScope:
    target_plan_count: int
    reason: str
    days: int

    def to_metrics(self) -> dict:
        return asdict(self)


def decide_recommendation_scope(request: TripRequest) -> RecommendationScope:
    days = max(1, int(request.days or 1))
    return RecommendationScope(
        target_plan_count=1,
        reason="default_single_plan",
        days=days,
    )
