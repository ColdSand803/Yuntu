"""Smoke test for POST /trip/async and GET /trip/jobs/{job_id} (no worker)."""

from __future__ import annotations

import asyncio
import os
import sys
import uuid

# Disable the in-process worker so this test only checks HTTP + DB persistence.
# A worker connected to the same shared database may still advance the job.
os.environ["TRIP_WORKER_ENABLED"] = "false"

import httpx
from httpx import ASGITransport
from sqlalchemy import text

from src.config import get_settings

get_settings.cache_clear()

from src.api.app import app
from src.pipeline.db import get_session_factory


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


async def main() -> None:
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        request_id = f"smoke:{uuid.uuid4().hex}"
        conversation_id = f"conv_smoke:{uuid.uuid4().hex}"
        message = "重庆3天 不想太累 喜欢美食和citywalk"

        create_resp = await client.post(
            "/trip/async",
            json={
                "message": message,
                "request_id": request_id,
                "source": "smoke-test",
                "conversation_id": conversation_id,
                "user_display_name": "灰度朋友",
            },
        )
        _assert(create_resp.status_code == 200, f"create failed: {create_resp.text}")
        created = create_resp.json()
        _assert(created.get("ok") is True, "create ok=false")
        _assert(created.get("cached") is False, "first create should not be cached")
        _assert(created.get("status") == "PENDING", "new job should be PENDING")
        job_id = created["job_id"]
        print(f"created job_id={job_id} queue_position={created.get('queue_position')}")
        async with get_session_factory()() as session:
            display_name = (await session.execute(
                text("""
                    SELECT user_display_name
                    FROM travel_trip_job
                    WHERE job_id = :job_id
                """),
                {"job_id": job_id},
            )).scalar_one()
        _assert(display_name == "灰度朋友", "user_display_name should be persisted")

        get_resp = await client.get(f"/trip/jobs/{job_id}")
        _assert(get_resp.status_code == 200, f"get failed: {get_resp.text}")
        status = get_resp.json()
        _assert(status.get("job_id") == job_id, "job_id mismatch")
        _assert(
            status.get("status") in {"PENDING", "RUNNING", "SUCCESS", "FAILED", "TIMEOUT", "REJECTED"},
            f"unexpected job status: {status.get('status')}",
        )
        if status.get("status") in {"PENDING", "RUNNING"}:
            _assert(status.get("result_record_id") is None, "non-terminal result_record_id should be null")
        _assert(status.get("elapsed_ms") is not None, "elapsed_ms should be present")
        print(f"GET status={status.get('status')} ok elapsed_ms={status.get('elapsed_ms')}")

        cached_resp = await client.post(
            "/trip/async",
            json={
                "message": message,
                "request_id": request_id,
                "source": "smoke-test",
                "conversation_id": conversation_id,
            },
        )
        _assert(cached_resp.status_code == 200, f"idempotent create failed: {cached_resp.text}")
        cached = cached_resp.json()
        _assert(cached.get("cached") is True, "idempotent hit should set cached=true")
        _assert(cached.get("job_id") == job_id, "idempotent hit should return same job_id")
        print("idempotent create ok")

        conflict_resp = await client.post(
            "/trip/async",
            json={
                "message": "重庆2天 完全不同",
                "request_id": request_id,
                "source": "smoke-test",
                "conversation_id": conversation_id,
            },
        )
        _assert(conflict_resp.status_code == 409, f"expected 409, got {conflict_resp.status_code}")
        conflict = conflict_resp.json()
        _assert(conflict.get("ok") is False, "409 body should have ok=false")
        print("409 conflict ok")

        missing_resp = await client.get("/trip/jobs/doesnotexist1234567890abcdef")
        _assert(missing_resp.status_code == 404, f"expected 404, got {missing_resp.status_code}")
        missing = missing_resp.json()
        _assert(missing.get("ok") is False, "404 body should have ok=false")
        print("404 missing job ok")

    print("\nasync API smoke test PASSED (worker not required)")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(f"async API smoke test FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
