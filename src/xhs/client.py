"""TikHub-backed Xiaohongshu App V2 client."""

from __future__ import annotations

import asyncio
import logging
import time

import httpx

from src.config import get_settings
from src.xhs.models import (
    NormalizedXhsNote,
    XhsSearchPage,
    normalize_note_detail,
    normalize_search_page,
)

logger = logging.getLogger(__name__)


class TikHubError(RuntimeError):
    code = "TIKHUB_UPSTREAM_FAILED"
    fatal = False


class TikHubAuthError(TikHubError):
    code = "TIKHUB_AUTH_FAILED"
    fatal = True


class TikHubBalanceError(TikHubError):
    code = "TIKHUB_BALANCE_INSUFFICIENT"
    fatal = True


class TikHubRateLimitError(TikHubError):
    code = "TIKHUB_RATE_LIMITED"


class TikHubResponseError(TikHubError):
    code = "TIKHUB_RESPONSE_INVALID"
    fatal = True


class XhsClient:
    """Provider-neutral XHS client implemented with TikHub App V2."""

    def __init__(
        self,
        token: str | None = None,
        *,
        base_url: str | None = None,
        rps: float | None = None,
    ):
        settings = get_settings()
        self.token = (token if token is not None else settings.tikhub_api_token).strip()
        self.base_url = (base_url or settings.tikhub_base_url).rstrip("/")
        self.rps = min(10.0, max(0.1, rps or settings.tikhub_rps))
        self.timeout = settings.tikhub_timeout_seconds
        self.max_retries = settings.tikhub_max_retries
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=self.timeout,
        )
        self._rate_lock = asyncio.Lock()
        self._last_request_at = 0.0

    async def _throttle(self) -> None:
        async with self._rate_lock:
            wait = (1.0 / self.rps) - (time.monotonic() - self._last_request_at)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request_at = time.monotonic()

    async def _get(self, path: str, params: dict) -> dict:
        if not self.token:
            raise TikHubAuthError("TIKHUB_API_TOKEN is not configured")
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            await self._throttle()
            try:
                response = await self._client.get(path, params=params)
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < self.max_retries:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise TikHubError(f"TikHub request failed: {exc}") from exc

            request_id = response.headers.get("x-request-id", "")
            if response.status_code in (401, 403):
                raise TikHubAuthError(f"TikHub authentication failed request_id={request_id}")
            if response.status_code == 402:
                raise TikHubBalanceError(f"TikHub balance insufficient request_id={request_id}")
            if response.status_code == 429:
                last_error = TikHubRateLimitError(
                    f"TikHub rate limited request_id={request_id}"
                )
                if attempt < self.max_retries:
                    retry_after = response.headers.get("retry-after")
                    await asyncio.sleep(float(retry_after) if retry_after else 2 ** attempt)
                    continue
                raise last_error
            if response.status_code >= 500:
                last_error = TikHubError(
                    f"TikHub upstream HTTP {response.status_code} request_id={request_id}"
                )
                if attempt < self.max_retries:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise last_error
            response.raise_for_status()
            try:
                payload = response.json()
            except ValueError as exc:
                raise TikHubResponseError(
                    f"TikHub returned invalid JSON request_id={request_id}"
                ) from exc
            if not isinstance(payload, dict):
                raise TikHubResponseError("TikHub response root is not an object")
            message = str(payload.get("message") or payload.get("msg") or "")
            lowered = message.lower()
            if "balance" in lowered or "余额" in message:
                raise TikHubBalanceError(message)
            outer_code = payload.get("code")
            if outer_code not in (None, 0, 200, "0", "200"):
                raise TikHubResponseError(
                    f"TikHub business error code={outer_code} message={message}"
                )
            inner = payload.get("data")
            if isinstance(inner, dict):
                inner_code = inner.get("code")
                inner_success = inner.get("success")
                inner_message = str(inner.get("message") or inner.get("msg") or "")
                if "余额" in inner_message or "balance" in inner_message.lower():
                    raise TikHubBalanceError(inner_message)
                if inner_success is False or inner_code not in (None, 0, 200, "0", "200"):
                    raise TikHubResponseError(
                        f"TikHub business error code={inner_code} "
                        f"message={inner_message}"
                    )
            return payload
        raise TikHubError(str(last_error or "TikHub request failed"))

    async def search_notes(
        self,
        keyword: str,
        page: int = 1,
        *,
        sort_type: str = "general",
        note_type: str = "不限",
        search_id: str | None = None,
        search_session_id: str | None = None,
    ) -> XhsSearchPage:
        params = {
            "keyword": keyword,
            "page": page,
            "sort_type": sort_type,
            "note_type": note_type,
        }
        if search_id:
            params["search_id"] = search_id
        if search_session_id:
            params["search_session_id"] = search_session_id
        return normalize_search_page(await self._get(
            "/api/v1/xiaohongshu/app_v2/search_notes",
            params,
        ))

    async def get_note_detail(
        self,
        note_id: str,
        note_type: str = "image",
    ) -> NormalizedXhsNote:
        endpoint = (
            "/api/v1/xiaohongshu/app_v2/get_video_note_detail"
            if note_type == "video"
            else "/api/v1/xiaohongshu/app_v2/get_image_note_detail"
        )
        payload = await self._get(endpoint, {"note_id": note_id})
        note = normalize_note_detail(payload, note_id=note_id, note_type=note_type)
        if not note.raw_text:
            raise TikHubResponseError(f"note {note_id} has no usable content")
        return note

    async def close(self) -> None:
        await self._client.aclose()
