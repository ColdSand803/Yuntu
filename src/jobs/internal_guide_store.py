"""Canonical one-result source lookup for the internal Admin contract."""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from sqlalchemy import text

from src.jobs.internal_admin_store import list_admin_artifacts
from src.jobs.projection_outbox import compute_guide_result_state, nullable_iso_utc, iso_utc
from src.pipeline.db import get_session_factory


REQUEST_FIELD_ALLOWLIST = frozenset(
    {
        "from_city",
        "to_city",
        "start_date",
        "end_date",
        "days",
        "people_count",
        "preferences",
        "avoid",
        "notes",
        "budget",
        "must_include",
        "commute_mode",
        "daily_start",
        "daily_end",
        "rest_windows",
        "accommodation",
    }
)
_TIME_RE = re.compile(r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")


def _public_filename(value: Any) -> str | None:
    filename = str(value or "").strip().replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = "".join(character for character in filename if ord(character) >= 32)
    return cleaned.strip() or None


def _object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def _project_rest_windows(value: Any) -> list[dict[str, Any]] | None:
    if not isinstance(value, list) or len(value) > 2:
        return None
    projected: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            return None
        start = str(item.get("start") or "").strip()
        end = str(item.get("end") or "").strip()
        label = item.get("label")
        if (
            not _TIME_RE.fullmatch(start)
            or not _TIME_RE.fullmatch(end)
            or (label is not None and len(str(label)) > 80)
        ):
            return None
        projected.append(
            {
                "start": start,
                "end": end,
                "label": (
                    str(label).strip()
                    if label is not None
                    else None
                ),
            }
        )
    return projected


def _project_request_value(field_name: str, value: Any) -> Any:
    if field_name in {"from_city", "to_city"}:
        if not isinstance(value, str) or len(value) > 120:
            return None
        if field_name == "to_city" and not value:
            return None
        return value
    if field_name in {"start_date", "end_date"}:
        if not isinstance(value, str):
            return None
        try:
            date.fromisoformat(value)
        except ValueError:
            return None
        return value
    if field_name in {"days", "people_count"}:
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        return value if 1 <= value <= 30 else None
    if field_name in {"preferences", "avoid"}:
        if (
            not isinstance(value, list)
            or len(value) > 20
            or any(
                not isinstance(item, str) or not item or len(item) > 80
                for item in value
            )
        ):
            return None
        return value
    if field_name == "notes":
        return value if isinstance(value, str) and len(value) <= 2000 else None
    if field_name == "budget":
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        return value if 0 <= value <= 10_000_000 else None
    if field_name == "must_include":
        if not isinstance(value, list) or len(value) > 5:
            return None
        projected_items: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, dict):
                return None
            name = item.get("name")
            place_id = item.get("place_id")
            if not isinstance(name, str) or not name or len(name) > 120:
                return None
            if place_id is not None and (
                isinstance(place_id, bool)
                or not isinstance(place_id, int)
                or place_id < 1
            ):
                return None
            projected_items.append({"name": name, "place_id": place_id})
        return projected_items
    if field_name == "commute_mode":
        return value if value in {"driving", "transit", "cycling"} else None
    if field_name in {"daily_start", "daily_end"}:
        return value if isinstance(value, str) and _TIME_RE.fullmatch(value) else None
    if field_name == "rest_windows":
        return _project_rest_windows(value)
    if field_name == "accommodation":
        if not isinstance(value, dict):
            return None
        name = str(value.get("name") or "").strip()
        if not name or len(name) > 160:
            return None
        place_id = value.get("place_id")
        latitude = value.get("latitude")
        longitude = value.get("longitude")
        if place_id is not None and (
            isinstance(place_id, bool)
            or not isinstance(place_id, int)
            or place_id < 1
        ):
            return None
        if latitude is not None and (
            isinstance(latitude, bool)
            or not isinstance(latitude, (int, float))
            or not -90 <= latitude <= 90
        ):
            return None
        if longitude is not None and (
            isinstance(longitude, bool)
            or not isinstance(longitude, (int, float))
            or not -180 <= longitude <= 180
        ):
            return None
        return {
            "name": name,
            "place_id": place_id,
            "latitude": latitude,
            "longitude": longitude,
        }
    return None


def project_structured_request(
    values_raw: Any,
    provenance_raw: Any,
) -> dict[str, Any] | None:
    """Return only immutable fields proven to have been supplied by the User."""
    source_values = _object(values_raw)
    source_provenance = _object(provenance_raw)
    values: dict[str, Any] = {}
    provenance: dict[str, str] = {}
    for field_name in sorted(REQUEST_FIELD_ALLOWLIST):
        if source_provenance.get(field_name) != "USER_SUPPLIED":
            continue
        if field_name not in source_values:
            continue
        projected = _project_request_value(field_name, source_values[field_name])
        if projected is None:
            continue
        values[field_name] = projected
        provenance[field_name] = "USER_SUPPLIED"
    if not values or set(values) != set(provenance):
        return None
    return {"values": values, "field_provenance": provenance}


async def get_internal_guide_source(job_id: str) -> dict[str, Any] | None:
    factory = get_session_factory()
    async with factory() as session:
        row = (
            await session.execute(
                text(
                    """
                    SELECT job_id, status, result_type, result_record_id,
                           guide_result_state, request_user_supplied_json,
                           request_field_provenance
                    FROM travel_trip_job
                    WHERE job_id = :job_id
                    """
                ),
                {"job_id": job_id},
            )
        ).mappings().one_or_none()
    if row is None:
        return None
    computed_state = compute_guide_result_state(
        status=str(row["status"]),
        result_type=row["result_type"],
        result_record_id=row["result_record_id"],
    )
    return {
        "job_id": str(row["job_id"]),
        "status": str(row["status"]),
        "result_type": row["result_type"],
        "result_record_id": (
            int(row["result_record_id"])
            if row["result_record_id"] is not None
            else None
        ),
        "guide_result_state": str(row["guide_result_state"]),
        "computed_guide_result_state": computed_state,
        "request": project_structured_request(
            row["request_user_supplied_json"],
            row["request_field_provenance"],
        ),
    }


async def get_internal_guide_artifacts(result_record_id: int) -> list[dict[str, Any]]:
    _total, items = await list_admin_artifacts(
        result_record_id=result_record_id,
        page=1,
        limit=100,
    )
    return [
        {
            "artifact_id": str(item["artifact_id"]),
            "artifact_type": str(item["artifact_type"]),
            "status": str(item["status"]),
            "filename": _public_filename(item.get("filename")),
            "mime_type": item.get("mime_type"),
            "byte_size": (
                int(item["byte_size"])
                if item.get("byte_size") is not None
                else None
            ),
            "created_at": iso_utc(item["created_time"]),
            "expires_at": nullable_iso_utc(item.get("expires_time")),
        }
        for item in items
    ]
