"""Access guard for public-but-protected travel APIs."""

from __future__ import annotations

import ipaddress
import logging
import secrets

from fastapi import HTTPException, Request

from src.config import get_settings

logger = logging.getLogger(__name__)


def _split_allowlist(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def _request_ip(request: Request) -> str:
    settings = get_settings()
    if settings.public_api_trust_proxy_headers:
        forwarded_for = request.headers.get("x-forwarded-for", "")
        if forwarded_for:
            first_hop = forwarded_for.split(",", 1)[0].strip()
            if first_hop:
                return first_hop
        real_ip = request.headers.get("x-real-ip", "").strip()
        if real_ip:
            return real_ip
    if request.client is not None and request.client.host:
        return request.client.host
    return ""


def _ip_allowed(client_ip: str, allowlist: list[str]) -> bool:
    if not client_ip:
        return False
    try:
        parsed_ip = ipaddress.ip_address(client_ip)
    except ValueError:
        return client_ip in allowlist

    for item in allowlist:
        try:
            if "/" in item:
                if parsed_ip in ipaddress.ip_network(item, strict=False):
                    return True
            elif parsed_ip == ipaddress.ip_address(item):
                return True
        except ValueError:
            if client_ip == item:
                return True
    return False


async def verify_public_api_client(request: Request) -> None:
    settings = get_settings()
    allowlist = _split_allowlist(settings.public_api_ip_allowlist)
    client_ip = _request_ip(request)
    if _ip_allowed(client_ip, allowlist):
        return

    logger.warning(
        "blocked public api client ip=%s path=%s allowlist_size=%s",
        client_ip or "unknown",
        request.url.path,
        len(allowlist),
    )
    raise HTTPException(
        status_code=403,
        detail={
            "code": "FORBIDDEN_CLIENT",
            "message": "client ip is not allowed",
        },
    )


async def verify_bff_internal_credential(request: Request) -> None:
    expected = get_settings().yuntu_travel_internal_credential.strip()
    supplied = (request.headers.get("X-Internal-Credential") or "").strip()
    if expected and supplied and secrets.compare_digest(expected, supplied):
        return
    logger.warning("blocked internal trip api path=%s", request.url.path)
    raise HTTPException(
        status_code=403,
        detail={
            "code": "FORBIDDEN_CLIENT",
            "message": "internal credential is invalid",
        },
    )
