"""Internal API token verification."""

from __future__ import annotations

import secrets

from fastapi import Header, HTTPException

from src.config import get_settings


async def verify_internal_token(
    x_internal_token: str | None = Header(None, alias="X-Internal-Token"),
) -> None:
    expected = get_settings().yuntu_travel_admin_token
    if not expected:
        raise HTTPException(status_code=500, detail="internal token is not configured")

    if not x_internal_token:
        raise HTTPException(status_code=401, detail="missing internal token")

    if not secrets.compare_digest(x_internal_token, expected):
        raise HTTPException(status_code=403, detail="invalid internal token")
