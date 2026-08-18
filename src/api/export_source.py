"""Export source builder for v0.8.11.1 backend artifacts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from src.api import trip_results

EXPORT_VERSION = "v0.9.5-schema-2.1-r1"


@dataclass(frozen=True)
class ExportSource:
    export_version: str
    source_hash: str
    canonical_json: str
    source: dict[str, Any]


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _source_hash(payload: dict[str, Any]) -> tuple[str, str]:
    canonical = _canonical_json(payload)
    return canonical, hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _day_source(day: dict[str, Any]) -> dict[str, Any]:
    return {
        "day": day["day"],
        "title": day["title"],
        "narrative": day.get("narrative", ""),
        "places": day.get("places", []),
        "commute_summary": day.get("commute_summary", ""),
        "commute_legs": day.get("commute_legs", []),
        "pace_status": day.get("pace_status"),
    }


def _plan_source(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "plan_id": plan["plan_id"],
        "title": plan["title"],
        "summary": plan["summary"],
        "tags": plan.get("tags", []),
        "pace": plan.get("pace"),
        "days": [_day_source(day) for day in plan.get("days", [])],
        "cost_estimate": plan["cost_estimate"],
    }


def build_export_source_from_trip_result(
    result: trip_results.TripResultResponse,
) -> ExportSource:
    projected = result.model_dump(mode="json", exclude_none=True)
    artifact_request = trip_results.artifact_request_fields(result)
    request = dict(projected["request"])
    request.update(artifact_request)
    source = {
        "export_version": EXPORT_VERSION,
        "result": {
            "schema_version": projected.get("schema_version"),
            "published_variant": projected["published_variant"],
            "delivery_status": projected["delivery_status"],
            "result_id": projected["result_id"],
            "city": projected["city"],
            "request": request,
            "weather": projected.get("weather"),
            "time_preferences": projected.get("time_preferences"),
            "must_include": projected.get("must_include", []),
            "plans": [
                _plan_source(plan)
                for plan in projected.get("plans", [])
            ],
        },
    }
    canonical, digest = _source_hash(source)
    return ExportSource(
        export_version=EXPORT_VERSION,
        source_hash=digest,
        canonical_json=canonical,
        source=source,
    )


async def build_export_source(result_record_id: int) -> ExportSource | None:
    result = await trip_results.get_trip_result(result_record_id)
    if result is None:
        return None
    return build_export_source_from_trip_result(result)
