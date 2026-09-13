"""Governed CDN city photography for the PDF cover."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from PIL import Image

from src.export.city_background import (
    CITY_BACKGROUND_ASSET_KEYS,
    fallback_city_background_with_metadata,
    open_image_bytes,
)


CATALOG_PATH = Path(__file__).resolve().parent / "assets" / "city_photo_catalog.json"
EXPECTED_BASE_URL = "https://assets.kakarot8.com"
OBJECT_KEY_PATTERN = re.compile(r"^city-opt/([a-z0-9-]+)/[A-Za-z0-9._-]+\.mobile\.jpg$")
MAX_DOWNLOAD_BYTES = 12 * 1024 * 1024
SUCCESS_CACHE_TTL_SECONDS = 4 * 60 * 60
FAILURE_CACHE_TTL_SECONDS = 60
SUCCESS_CACHE_MAX_ITEMS = 32


class CityPhotoCatalogError(RuntimeError):
    pass


class CityPhotoFetchError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class CityPhotoEntry:
    city: str
    folder: str
    object_key: str
    sha256: str
    provider: str
    author: str
    source_page_url: str
    license: str
    license_url: str | None

    @property
    def short_credit(self) -> str:
        return f"摄影：{self.author} · 来源：{self.provider} · 许可：{self.license}"

    @property
    def modification_notice(self) -> str:
        return "云途为版式需要进行了裁切与调色。"


@dataclass(frozen=True)
class CityPhotoResult:
    image: Image.Image
    entry: CityPhotoEntry | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class _CacheValue:
    expires_at: float
    image_bytes: bytes | None
    error_code: str | None


class CityPhotoResolver:
    """Resolve a fixed catalog object or fail open to a packaged background."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 5.0,
        http_transport: Any | None = None,
        clock: Callable[[], float] = time.monotonic,
        catalog_path: Path = CATALOG_PATH,
    ) -> None:
        self.timeout_seconds = min(5.0, max(0.1, float(timeout_seconds)))
        self.http_transport = http_transport
        self._clock = clock
        self.catalog_revision, self.base_url, self._entries = _load_catalog(catalog_path)
        self._cache: OrderedDict[str, _CacheValue] = OrderedDict()
        self._cache_lock = threading.Lock()
        self._key_locks: dict[str, threading.Lock] = {}

    def resolve(self, city: str) -> CityPhotoResult:
        normalized = normalize_city_name(city)
        entry = self._entries.get(normalized)
        if entry is None:
            return self._fallback(normalized, "photo_city_not_cataloged")

        key_lock = self._lock_for(entry.object_key)
        with key_lock:
            cached = self._cached(entry.object_key)
            if cached is not None:
                if cached.image_bytes is not None:
                    return self._success(entry, cached.image_bytes, cache_hit=True)
                return self._fallback(normalized, cached.error_code or "photo_fetch_failed", failure_cache_hit=True)

            try:
                image_bytes = self._download(entry)
            except CityPhotoFetchError as exc:
                self._store(entry.object_key, None, exc.code, FAILURE_CACHE_TTL_SECONDS)
                return self._fallback(normalized, exc.code)

            self._store(entry.object_key, image_bytes, None, SUCCESS_CACHE_TTL_SECONDS)
            return self._success(entry, image_bytes, cache_hit=False)

    def _download(self, entry: CityPhotoEntry) -> bytes:
        import httpx

        url = f"{self.base_url}/{entry.object_key}"
        timeout = httpx.Timeout(self.timeout_seconds, connect=min(2.0, self.timeout_seconds))
        try:
            with httpx.Client(
                timeout=timeout,
                transport=self.http_transport,
                follow_redirects=False,
            ) as client:
                with client.stream("GET", url) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        raise CityPhotoFetchError("photo_redirect_rejected")
                    if response.status_code != 200:
                        raise CityPhotoFetchError("photo_http_error")
                    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    if content_type != "image/jpeg":
                        raise CityPhotoFetchError("photo_content_type_invalid")
                    declared = response.headers.get("content-length")
                    if declared:
                        try:
                            if int(declared) > MAX_DOWNLOAD_BYTES:
                                raise CityPhotoFetchError("photo_size_exceeded")
                        except ValueError:
                            raise CityPhotoFetchError("photo_content_length_invalid") from None
                    chunks: list[bytes] = []
                    byte_count = 0
                    for chunk in response.iter_bytes():
                        byte_count += len(chunk)
                        if byte_count > MAX_DOWNLOAD_BYTES:
                            raise CityPhotoFetchError("photo_size_exceeded")
                        chunks.append(chunk)
        except CityPhotoFetchError:
            raise
        except httpx.TimeoutException as exc:
            raise CityPhotoFetchError("photo_timeout") from exc
        except httpx.HTTPError as exc:
            raise CityPhotoFetchError("photo_network_error") from exc

        image_bytes = b"".join(chunks)
        digest = hashlib.sha256(image_bytes).hexdigest()
        if not hmac.compare_digest(digest, entry.sha256):
            raise CityPhotoFetchError("photo_digest_mismatch")
        try:
            open_image_bytes(image_bytes)
        except Exception as exc:
            raise CityPhotoFetchError("photo_decode_invalid") from exc
        return image_bytes

    def _success(self, entry: CityPhotoEntry, image_bytes: bytes, *, cache_hit: bool) -> CityPhotoResult:
        return CityPhotoResult(
            image=open_image_bytes(image_bytes),
            entry=entry,
            metadata={
                "background_status": "cdn",
                "photo_status": "cdn",
                "photo_catalog_revision": self.catalog_revision,
                "photo_object_key": entry.object_key,
                "photo_sha256": entry.sha256,
                "photo_cache_hit": cache_hit,
                "photo_author": entry.author,
                "photo_provider": entry.provider,
                "photo_license": entry.license,
                "ai_call_attempted": False,
                "ai_call_count": 0,
            },
        )

    def _fallback(
        self,
        city: str,
        error_code: str,
        *,
        failure_cache_hit: bool = False,
    ) -> CityPhotoResult:
        key = CITY_BACKGROUND_ASSET_KEYS.get(city)
        image, fallback_metadata = fallback_city_background_with_metadata(key)
        return CityPhotoResult(
            image=image,
            entry=None,
            metadata={
                "background_status": "fallback",
                "photo_status": "fallback",
                "photo_catalog_revision": self.catalog_revision,
                "photo_cache_hit": False,
                "photo_failure_cache_hit": failure_cache_hit,
                "photo_error_code": error_code,
                "ai_call_attempted": False,
                "ai_call_count": 0,
                **fallback_metadata,
            },
        )

    def _lock_for(self, key: str) -> threading.Lock:
        with self._cache_lock:
            return self._key_locks.setdefault(key, threading.Lock())

    def _cached(self, key: str) -> _CacheValue | None:
        now = self._clock()
        with self._cache_lock:
            value = self._cache.get(key)
            if value is None:
                return None
            if value.expires_at <= now:
                self._cache.pop(key, None)
                return None
            self._cache.move_to_end(key)
            return value

    def _store(self, key: str, image_bytes: bytes | None, error_code: str | None, ttl: int) -> None:
        with self._cache_lock:
            self._cache[key] = _CacheValue(self._clock() + ttl, image_bytes, error_code)
            self._cache.move_to_end(key)
            while len(self._cache) > SUCCESS_CACHE_MAX_ITEMS:
                self._cache.popitem(last=False)


def build_city_photo_resolver(settings: Any | None = None) -> CityPhotoResolver | None:
    if settings is None:
        from src.config import get_settings

        settings = get_settings()
    if not bool(getattr(settings, "export_pdf_city_photo_enabled", True)):
        return None
    return CityPhotoResolver(
        timeout_seconds=float(getattr(settings, "export_pdf_city_photo_timeout_seconds", 5.0)),
    )


def normalize_city_name(value: str) -> str:
    normalized = re.sub(r"\s+", "", str(value or "")).strip()
    if normalized.endswith("市"):
        normalized = normalized[:-1]
    return normalized


def _load_catalog(path: Path) -> tuple[str, str, dict[str, CityPhotoEntry]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CityPhotoCatalogError("city photo catalog is unreadable") from exc
    revision = str(payload.get("catalog_revision") or "").strip()
    base_url = str(payload.get("base_url") or "").rstrip("/")
    photos = payload.get("photos")
    if not revision or base_url != EXPECTED_BASE_URL or not isinstance(photos, list):
        raise CityPhotoCatalogError("city photo catalog header is invalid")

    entries: dict[str, CityPhotoEntry] = {}
    for item in photos:
        if not isinstance(item, dict):
            raise CityPhotoCatalogError("city photo catalog entry is invalid")
        required = (
            "city", "folder", "object_key", "sha256", "provider", "author",
            "source_page_url", "license", "rights_status",
            "city_assignment_status", "publish_status",
        )
        if any(not str(item.get(field) or "").strip() for field in required):
            raise CityPhotoCatalogError("city photo catalog entry is incomplete")
        city = normalize_city_name(str(item["city"]))
        folder = str(item["folder"])
        object_key = str(item["object_key"])
        match = OBJECT_KEY_PATTERN.fullmatch(object_key)
        digest = str(item["sha256"]).lower()
        if not city or city in entries or match is None or match.group(1) != folder:
            raise CityPhotoCatalogError("city photo catalog key is invalid")
        if not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise CityPhotoCatalogError("city photo digest is invalid")
        if item["rights_status"] != "owner_confirmed" or item["publish_status"] != "approved":
            raise CityPhotoCatalogError("city photo governance status is invalid")
        if item["city_assignment_status"] not in {
            "source_metadata_verified",
            "source_location_verified",
            "landmark_verified",
        }:
            raise CityPhotoCatalogError("city photo assignment status is invalid")
        source_url = str(item["source_page_url"])
        license_url = str(item["license_url"]) if item.get("license_url") else None
        if urlparse(source_url).scheme != "https":
            raise CityPhotoCatalogError("city photo source URL is invalid")
        if license_url and urlparse(license_url).scheme not in {"http", "https"}:
            raise CityPhotoCatalogError("city photo license URL is invalid")
        entries[city] = CityPhotoEntry(
            city=city,
            folder=folder,
            object_key=object_key,
            sha256=digest,
            provider=str(item["provider"]),
            author=str(item["author"]),
            source_page_url=source_url,
            license=str(item["license"]),
            license_url=license_url,
        )
    return revision, base_url, entries
