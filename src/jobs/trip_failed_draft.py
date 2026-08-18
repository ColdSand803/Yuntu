"""Safe, terminal-only persistence for failed trip Writer drafts."""

from __future__ import annotations

import json
from typing import Any, Iterable

from sqlalchemy import text

from src.agents.schema import PlanOutput
from src.jobs.projection_outbox import emit_trip_projection_commit
from src.pipeline.db import get_session_factory


SAFE_PLAN_FIELDS = frozenset(
    {
        "plan_name",
        "summary",
        "plan_text",
        "used_place_names",
        "day_place_names",
    }
)


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _names(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _day_names(value: Any) -> list[list[str]]:
    if not isinstance(value, list):
        return []
    return [_names(day) for day in value if isinstance(day, list)]


def project_failed_draft_plans(
    plans: Iterable[PlanOutput | dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return only the frozen Writer-safe failed-draft projection."""
    projected: list[dict[str, Any]] = []
    for plan in plans:
        if isinstance(plan, PlanOutput):
            item = {
                "plan_name": plan.plan_name,
                "summary": plan.summary,
                "plan_text": plan.plan_text,
                "used_place_names": list(plan.used_place_names),
                "day_place_names": [
                    list(day_names) for day_names in plan.day_place_names
                ],
            }
        elif isinstance(plan, dict):
            item = {
                "plan_name": _text(plan.get("plan_name")),
                "summary": _text(plan.get("summary")),
                "plan_text": _text(plan.get("plan_text")),
                "used_place_names": _names(plan.get("used_place_names")),
                "day_place_names": _day_names(plan.get("day_place_names")),
            }
        else:
            continue

        # A Writer that produced no body must not create a failed draft.
        if not item["plan_text"].strip():
            continue
        projected.append(item)
    return projected


async def persist_failed_draft_if_eligible(
    job_id: str,
    plans: Iterable[PlanOutput | dict[str, Any]],
) -> bool:
    """Insert one immutable snapshot after a job is durably FAILED/TIMEOUT."""
    snapshot = project_failed_draft_plans(plans)
    if not snapshot:
        return False

    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text(
                """
                INSERT INTO travel_trip_failed_draft (job_id, plans_json)
                SELECT job_id, CAST(:plans_json AS jsonb)
                FROM travel_trip_job
                WHERE job_id = :job_id
                  AND status IN ('FAILED', 'TIMEOUT')
                  AND COALESCE(result_type, '') NOT IN (
                      'NO_CANDIDATES',
                      'NO_USABLE_ROUTE'
                  )
                ON CONFLICT (job_id) DO NOTHING
                RETURNING job_id
                """
            ),
            {
                "job_id": job_id,
                "plans_json": json.dumps(
                    snapshot,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            },
        )
        inserted = result.scalar_one_or_none() is not None
        if inserted:
            await emit_trip_projection_commit(session, job_id=job_id)
        await session.commit()
    return inserted
