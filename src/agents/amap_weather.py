"""Amap weather client for v0.8.0 Weather Enrichment."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from src.agents.weather_advisory import (
    STATUS_API_ERROR,
    STATUS_FORBIDDEN,
    STATUS_RATE_LIMITED,
    STATUS_TIMEOUT,
)

logger = logging.getLogger(__name__)

AMAP_WEATHER_URL = "https://restapi.amap.com/v3/weather/weatherInfo"


class AmapWeatherError(RuntimeError):
    def __init__(self, status: str, message: str = "") -> None:
        super().__init__(message or status)
        self.status = status


class AmapWeatherClient:
    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: float = 5.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self._client = client

    async def fetch_daily_forecast(self, *, adcode: str) -> list[dict[str, Any]]:
        params = {
            "key": self.api_key,
            "city": adcode,
            "extensions": "all",
            "output": "JSON",
        }
        try:
            if self._client is not None:
                response = await self._client.get(
                    AMAP_WEATHER_URL,
                    params=params,
                    timeout=self.timeout_seconds,
                )
            else:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    response = await client.get(AMAP_WEATHER_URL, params=params)
        except httpx.TimeoutException as exc:
            raise AmapWeatherError(STATUS_TIMEOUT, str(exc)) from exc
        except httpx.TransportError as exc:
            raise AmapWeatherError(STATUS_API_ERROR, str(exc)) from exc

        if response.status_code in {401, 403}:
            raise AmapWeatherError(STATUS_FORBIDDEN, response.text[:200])
        if response.status_code == 429:
            raise AmapWeatherError(STATUS_RATE_LIMITED, response.text[:200])
        if response.status_code >= 400:
            raise AmapWeatherError(STATUS_API_ERROR, response.text[:200])

        try:
            payload = response.json()
        except ValueError as exc:
            raise AmapWeatherError(STATUS_API_ERROR, "invalid json") from exc

        if str(payload.get("status") or "") != "1":
            infocode = str(payload.get("infocode") or "")
            info = str(payload.get("info") or "")
            status = _status_from_infocode(infocode, info)
            raise AmapWeatherError(status, f"{infocode}:{info}")

        forecasts = payload.get("forecasts")
        if not isinstance(forecasts, list) or not forecasts:
            raise AmapWeatherError(STATUS_API_ERROR, "missing forecasts")
        casts = forecasts[0].get("casts") if isinstance(forecasts[0], dict) else None
        if not isinstance(casts, list):
            raise AmapWeatherError(STATUS_API_ERROR, "missing casts")
        return [item for item in casts if isinstance(item, dict)]


def _status_from_infocode(infocode: str, info: str) -> str:
    text = f"{infocode} {info}".lower()
    if infocode in {"10001", "10002", "10009", "10010"}:
        return STATUS_FORBIDDEN
    if infocode in {"10003", "10004"} or "quota" in text or "limit" in text:
        return STATUS_RATE_LIMITED
    return STATUS_API_ERROR
