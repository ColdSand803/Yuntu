"""Single-plan repair with explicit inputs."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from src.agents import final_writer
from src.agents.evidence_strength import StructuredEvidencePayload
from src.agents.generation_issues import GenerationIssue
from src.agents.schema import PlanOutput, RoutePlan, TripRequest
from src.agents.weather_advisory import WeatherAdvisoryPayload


def _serialize_sanitizer_action(action: Any) -> dict[str, Any]:
    if hasattr(action, "model_dump"):
        return action.model_dump(mode="json")
    if isinstance(action, dict):
        return action
    return {"action": str(action), "reason": "unknown_sanitizer_action"}


@dataclass
class PlanRepairResult:
    plan_index: int
    zero_index: int
    repaired_plan: PlanOutput | None = None
    failure_reason: str = ""
    failure_detail: dict[str, Any] | None = None
    sanitizer_actions: list[dict[str, Any]] = field(default_factory=list)
    repair_metrics: dict[str, Any] = field(default_factory=dict)
    latency_ms: int = 0


async def repair_single_plan(
    *,
    plan_index: int,
    plans: list[PlanOutput],
    route_plans: list[RoutePlan],
    trip_request: TripRequest,
    retrieval_city: str,
    issues: list[GenerationIssue],
    budget_results: list | None,
    poi_identity_results: list | None,
    composition_blueprints: list | None,
    validation_candidate_names: list[str],
    structured_evidence_payload: StructuredEvidencePayload | None = None,
    weather_advisory_payload: WeatherAdvisoryPayload | None = None,
) -> PlanRepairResult:
    """Repair one plan and return a normal structured failure result."""
    zero_index = plan_index - 1
    if zero_index < 0 or zero_index >= len(plans):
        return PlanRepairResult(
            plan_index=plan_index,
            zero_index=zero_index,
            failure_reason=f"invalid_repair_target:{plan_index}",
        )
    if not route_plans or zero_index >= len(route_plans):
        return PlanRepairResult(
            plan_index=plan_index,
            zero_index=zero_index,
            failure_reason=f"missing_route_plan:{plan_index}",
        )

    t0 = time.monotonic()
    repair_result = await final_writer.repair_plan(
        trip_request=trip_request,
        retrieval_city=retrieval_city,
        original_plan=plans[zero_index],
        route_plan=route_plans[zero_index],
        issues=issues,
        budget_result=(
            budget_results[zero_index]
            if budget_results and zero_index < len(budget_results)
            else None
        ),
        poi_identity_result=(
            poi_identity_results[zero_index]
            if poi_identity_results and zero_index < len(poi_identity_results)
            else None
        ),
        composition_blueprint=(
            composition_blueprints[zero_index]
            if composition_blueprints and zero_index < len(composition_blueprints)
            else None
        ),
        validation_candidate_names=validation_candidate_names,
        plan_index=plan_index,
        return_result=True,
        structured_evidence_payload=structured_evidence_payload,
        weather_advisory_payload=weather_advisory_payload,
    )
    latency_ms = int((time.monotonic() - t0) * 1000)

    repaired_plan = None
    failure_detail = None
    sanitizer_actions: list[dict[str, Any]] = []
    repair_metrics: dict[str, Any] = {}
    if isinstance(repair_result, final_writer.RepairPlanResult):
        repaired_plan = repair_result.plan
        failure_detail = repair_result.failure_detail
        sanitizer_actions = [
            _serialize_sanitizer_action(action)
            for action in repair_result.sanitizer_actions
        ]
        repair_metrics = repair_result.metrics
    else:
        repaired_plan = repair_result

    if repaired_plan is None:
        detail_payload = (
            failure_detail.model_dump(mode="json")
            if failure_detail is not None
            else {"plan_index": plan_index, "reason": f"repair_failed:{plan_index}"}
        )
        return PlanRepairResult(
            plan_index=plan_index,
            zero_index=zero_index,
            failure_reason=f"repair_failed:{plan_index}",
            failure_detail=detail_payload,
            sanitizer_actions=sanitizer_actions,
            repair_metrics=repair_metrics,
            latency_ms=latency_ms,
        )

    return PlanRepairResult(
        plan_index=plan_index,
        zero_index=zero_index,
        repaired_plan=repaired_plan,
        failure_detail=(
            failure_detail.model_dump(mode="json")
            if failure_detail is not None
            else None
        ),
        sanitizer_actions=sanitizer_actions,
        repair_metrics=repair_metrics,
        latency_ms=latency_ms,
    )
