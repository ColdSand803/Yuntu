"""Repair budget and policy for the write-review-publish pipeline."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
import os
from pathlib import Path

from src.config import get_settings


class RepairBudgetExceeded(RuntimeError):
    def __init__(self, *, elapsed_seconds: float, max_wall_seconds: float):
        self.elapsed_seconds = elapsed_seconds
        self.max_wall_seconds = max_wall_seconds
        super().__init__(
            f"repair wall time {elapsed_seconds:.1f}s exceeded "
            f"budget {max_wall_seconds:.1f}s"
        )


@dataclass(frozen=True)
class RepairPolicy:
    max_followup_rounds: int = 2
    max_wall_seconds: float = 210.0
    per_plan_timeout_seconds: float = 90.0
    max_target_plans_per_round: int = 3

    @classmethod
    def from_settings(cls) -> "RepairPolicy":
        settings = get_settings()
        configured_wall = _explicit_env_value("WRITER_REPAIR_MAX_WALL_SECONDS")
        max_wall_seconds = (
            float(configured_wall)
            if configured_wall is not None
            else 210.0
        )
        return cls(
            max_followup_rounds=max(
                0,
                int(getattr(settings, "writer_repair_max_followup_rounds", 2)),
            ),
            max_wall_seconds=max(
                1.0,
                max_wall_seconds,
            ),
            per_plan_timeout_seconds=max(
                1.0,
                float(getattr(settings, "writer_repair_per_plan_timeout_seconds", 90.0)),
            ),
            max_target_plans_per_round=max(
                1,
                int(getattr(settings, "writer_repair_max_target_plans_per_round", 3)),
            ),
        )

    def start_budget(
        self,
        *,
        days: int | None = None,
        issue_count: int = 0,
        target_plan_count: int = 1,
    ) -> "RepairBudgetTracker":
        if days is None:
            computed = self.max_wall_seconds
            days = 0
        else:
            computed = (
                90.0
                + max(1, int(days)) * 15.0
                + max(1, int(target_plan_count)) * 20.0
                + min(max(0, int(issue_count)), 4) * 10.0
            )
        max_wall_seconds = min(computed, self.max_wall_seconds)
        return RepairBudgetTracker(
            policy=self,
            max_wall_seconds=max_wall_seconds,
            computed_wall_seconds=computed,
            days=max(0, int(days or 0)),
            issue_count=max(0, int(issue_count)),
            target_plan_count=max(1, int(target_plan_count)),
        )


@dataclass
class RepairBudgetTracker:
    policy: RepairPolicy
    max_wall_seconds: float
    computed_wall_seconds: float
    days: int
    issue_count: int
    target_plan_count: int
    started_at: float = field(default_factory=time.monotonic)

    def elapsed_seconds(self) -> float:
        return time.monotonic() - self.started_at

    def remaining_seconds(self) -> float:
        return self.max_wall_seconds - self.elapsed_seconds()

    def assert_can_continue(self) -> None:
        elapsed = self.elapsed_seconds()
        if elapsed > self.max_wall_seconds:
            raise RepairBudgetExceeded(
                elapsed_seconds=elapsed,
                max_wall_seconds=self.max_wall_seconds,
            )

    def to_metrics(self, *, exceeded: bool = False) -> dict:
        return {
            "computed_wall_seconds": round(self.computed_wall_seconds, 1),
            "max_wall_seconds": round(self.max_wall_seconds, 1),
            "elapsed_seconds": round(self.elapsed_seconds(), 1),
            "exceeded": exceeded,
            "days": self.days,
            "issue_count": self.issue_count,
            "target_plan_count": self.target_plan_count,
        }


def _explicit_env_value(name: str) -> str | None:
    value = os.environ.get(name)
    if value is not None:
        return value
    env_path = Path(".env")
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, raw_value = stripped.split("=", 1)
        if key.strip().upper() == name:
            return raw_value.strip().strip("'\"")
    return None
