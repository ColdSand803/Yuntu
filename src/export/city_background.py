"""Shared city-background generation for PDF and share-image artifacts."""

from __future__ import annotations

import base64
import ipaddress
import json
import re
import socket
import threading
import time
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.parse import urljoin, urlparse

from PIL import Image, ImageDraw, ImageFilter


FALLBACK_BACKGROUND_PATH = Path(__file__).resolve().parent / "assets" / "share_fallback.png"
CITY_BACKGROUND_ASSET_DIR = Path(__file__).resolve().parent / "assets" / "city_backgrounds"
CITY_BACKGROUND_ASSET_KEYS = {
    "北京": "beijing",
    "上海": "shanghai",
    "重庆": "chongqing",
    "成都": "chengdu",
    "杭州": "hangzhou",
    "西安": "xian",
    "南京": "nanjing",
    "长沙": "changsha",
    "青岛": "qingdao",
    "桂林": "guilin",
}
IMAGE_DOWNLOAD_TIMEOUT_SECONDS = 30.0
IMAGE_DOWNLOAD_MAX_BYTES = 12 * 1024 * 1024
IMAGE_DOWNLOAD_MAX_REDIRECTS = 3
IMAGE_MAX_DIMENSION = 4096
IMAGE_MAX_PIXELS = 16_000_000
ALLOWED_IMAGE_CONTENT_TYPES = {"image/png", "image/jpeg", "image/webp"}
REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}
IMAGE_PROVIDER_API_MODES = {"chat_completions", "images_generations"}
IMAGE_PROVIDER_MAX_ATTEMPTS_HARD_LIMIT = 2
IMAGE_PROVIDER_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


@dataclass(frozen=True)
class GeneratedCityBackground:
    image_bytes: bytes
    metadata: dict[str, Any]


@dataclass(frozen=True)
class ImageProviderChannel:
    name: str
    base_url: str
    api_key: str
    model: str
    api_mode: str


class PooledBackgroundGenerationError(RuntimeError):
    def __init__(self, error_code: str, metadata: dict[str, Any]) -> None:
        super().__init__(error_code)
        self.error_code = error_code
        self.metadata = metadata


class CityBackgroundClient(Protocol):
    def generate_background(self, prompt: str) -> bytes | GeneratedCityBackground:
        ...


class OpenAIChatImageBackgroundClient:
    """OpenAI-compatible chat-completions image client configured by Settings."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float,
        http_transport: Any | None = None,
        dns_resolver: Callable[[str, int | None], list[str]] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.http_transport = http_transport
        self.dns_resolver = dns_resolver or _resolve_hostname_ips

    @classmethod
    def from_settings(cls, settings: Any | None = None) -> "OpenAIChatImageBackgroundClient | None":
        if settings is None:
            from src.config import get_settings

            settings = get_settings()
        base_url = str(getattr(settings, "export_image_api_base_url", "") or "").strip()
        api_key = str(getattr(settings, "export_image_api_key", "") or "").strip()
        model = str(getattr(settings, "export_image_model", "") or "").strip()
        if not base_url or not api_key or not model:
            return None
        return cls(
            base_url=base_url,
            api_key=api_key,
            model=model,
            timeout_seconds=_positive_float(
                getattr(settings, "export_image_timeout_seconds", 360.0),
                360.0,
            ),
        )

    def generate_background(self, prompt: str) -> bytes:
        import httpx

        with httpx.Client(
            timeout=self.timeout_seconds,
            transport=self.http_transport,
            follow_redirects=False,
        ) as client:
            response = client.post(
                self._completion_url(),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            response.raise_for_status()
            content = message_content(response.json())
            image_bytes = extract_base64_image(content)
            if image_bytes is None:
                image_url = extract_markdown_image_url(content)
                if image_url is None:
                    raise ValueError("image response did not contain a supported image")
                image_bytes = self._download_image(client, image_url)
        open_image_bytes(image_bytes)
        return image_bytes

    def _download_image(self, client: Any, image_url: str) -> bytes:
        next_url = _validate_http_image_url(image_url, dns_resolver=self.dns_resolver)
        redirects_followed = 0
        while True:
            with client.stream(
                "GET",
                next_url,
                timeout=min(self.timeout_seconds, IMAGE_DOWNLOAD_TIMEOUT_SECONDS),
            ) as response:
                if response.status_code in REDIRECT_STATUS_CODES:
                    if redirects_followed >= IMAGE_DOWNLOAD_MAX_REDIRECTS:
                        raise ValueError("image download exceeded redirect limit")
                    location = response.headers.get("location")
                    if not location or not location.strip():
                        raise ValueError("image download redirect location is missing")
                    next_url = _validate_http_image_url(
                        urljoin(next_url, location.strip()),
                        dns_resolver=self.dns_resolver,
                    )
                    redirects_followed += 1
                    continue
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
                    raise ValueError("image download content type is not allowed")
                content_length = response.headers.get("content-length")
                if content_length:
                    try:
                        declared_length = int(content_length)
                    except ValueError:
                        raise ValueError("image download content length is invalid") from None
                    if declared_length > IMAGE_DOWNLOAD_MAX_BYTES:
                        raise ValueError("image download exceeds maximum size")
                chunks: list[bytes] = []
                byte_count = 0
                for chunk in response.iter_bytes():
                    byte_count += len(chunk)
                    if byte_count > IMAGE_DOWNLOAD_MAX_BYTES:
                        raise ValueError("image download exceeds maximum size")
                    chunks.append(chunk)
            return b"".join(chunks)

    def _completion_url(self) -> str:
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/chat/completions"
        return f"{self.base_url}/v1/chat/completions"


class OpenAIImagesGenerationClient(OpenAIChatImageBackgroundClient):
    """OpenAI-compatible images/generations client with protected URL fallback."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float,
        size: str = "1024x1536",
        quality: str = "standard",
        style: str = "vivid",
        response_format: str = "b64_json",
        http_transport: Any | None = None,
        dns_resolver: Callable[[str, int | None], list[str]] | None = None,
    ) -> None:
        super().__init__(
            base_url=base_url,
            api_key=api_key,
            model=model,
            timeout_seconds=timeout_seconds,
            http_transport=http_transport,
            dns_resolver=dns_resolver,
        )
        self.size = size
        self.quality = quality
        self.style = style
        self.response_format = response_format

    @classmethod
    def from_settings(cls, settings: Any | None = None) -> "OpenAIImagesGenerationClient | None":
        if settings is None:
            from src.config import get_settings

            settings = get_settings()
        base_url = str(getattr(settings, "export_image_api_base_url", "") or "").strip()
        api_key = str(getattr(settings, "export_image_api_key", "") or "").strip()
        model = str(getattr(settings, "export_image_model", "") or "").strip()
        if not base_url or not api_key or not model:
            return None
        return cls(
            base_url=base_url,
            api_key=api_key,
            model=model,
            timeout_seconds=_positive_float(
                getattr(settings, "export_image_timeout_seconds", 360.0),
                360.0,
            ),
            size=str(getattr(settings, "export_image_size", "1024x1536") or "1024x1536").strip(),
            quality=str(getattr(settings, "export_image_quality", "standard") or "standard").strip(),
            style=str(getattr(settings, "export_image_style", "vivid") or "vivid").strip(),
            response_format=str(
                getattr(settings, "export_image_response_format", "b64_json") or "b64_json"
            ).strip(),
        )

    def generate_background(self, prompt: str) -> bytes:
        import httpx

        with httpx.Client(
            timeout=self.timeout_seconds,
            transport=self.http_transport,
            follow_redirects=False,
        ) as client:
            response = client.post(
                self._generation_url(),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "size": self.size,
                    "quality": self.quality,
                    "style": self.style,
                    "n": 1,
                    "response_format": self.response_format,
                },
            )
            response.raise_for_status()
            item = first_image_data(response.json())
            encoded = item.get("b64_json")
            if isinstance(encoded, str) and encoded.strip():
                image_bytes = decode_base64_image(encoded)
            else:
                image_url = item.get("url")
                if not isinstance(image_url, str) or not image_url.strip():
                    raise ValueError("image response did not contain b64_json or URL")
                image_bytes = self._download_image(client, image_url.strip())
        open_image_bytes(image_bytes)
        return image_bytes

    def _generation_url(self) -> str:
        if self.base_url.endswith("/images/generations"):
            return self.base_url
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/images/generations"
        return f"{self.base_url}/v1/images/generations"


def build_city_background_client(settings: Any | None = None) -> CityBackgroundClient | None:
    """Build the configured image client while keeping chat mode backward compatible."""

    if settings is None:
        from src.config import get_settings

        settings = get_settings()
    channels = parse_image_provider_pool(
        getattr(settings, "export_image_provider_pool", "")
    )
    if channels:
        clients = tuple(
            (channel, _build_channel_client(channel, settings))
            for channel in channels
        )
        return PooledCityBackgroundClient(
            clients,
            max_attempts=_bounded_provider_attempts(
                getattr(settings, "export_image_provider_max_attempts", 2)
            ),
            cooldown_seconds=_positive_float(
                getattr(settings, "export_image_provider_cooldown_seconds", 600.0),
                600.0,
            ),
        )

    mode = str(getattr(settings, "export_image_api_mode", "chat_completions") or "").strip().lower()
    if mode == "chat_completions":
        return OpenAIChatImageBackgroundClient.from_settings(settings)
    if mode == "images_generations":
        return OpenAIImagesGenerationClient.from_settings(settings)
    raise ValueError(f"unsupported EXPORT_IMAGE_API_MODE: {mode or '<empty>'}")


def parse_image_provider_pool(value: Any) -> tuple[ImageProviderChannel, ...]:
    """Parse and validate provider channels without exposing their credentials."""

    if value is None or (isinstance(value, str) and not value.strip()):
        return ()
    try:
        payload = json.loads(value) if isinstance(value, str) else value
    except json.JSONDecodeError as exc:
        raise ValueError("EXPORT_IMAGE_PROVIDER_POOL must be valid JSON") from exc
    if not isinstance(payload, list):
        raise ValueError("EXPORT_IMAGE_PROVIDER_POOL must be a JSON array")

    channels: list[ImageProviderChannel] = []
    names: set[str] = set()
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise ValueError(f"EXPORT_IMAGE_PROVIDER_POOL[{index}] must be an object")
        fields = {
            field: str(item.get(field, "") or "").strip()
            for field in ("name", "base_url", "api_key", "model", "api_mode")
        }
        missing = [field for field, content in fields.items() if not content]
        if missing:
            raise ValueError(
                f"EXPORT_IMAGE_PROVIDER_POOL[{index}] missing required field: {missing[0]}"
            )
        name = fields["name"]
        if not IMAGE_PROVIDER_NAME_PATTERN.fullmatch(name):
            raise ValueError(
                f"EXPORT_IMAGE_PROVIDER_POOL[{index}].name must use safe ASCII characters"
            )
        if name in names:
            raise ValueError(f"duplicate image provider channel name: {name}")
        mode = fields["api_mode"].lower()
        if mode not in IMAGE_PROVIDER_API_MODES:
            raise ValueError(
                f"unsupported image provider api_mode for channel {name}: {mode}"
            )
        _validate_http_url(fields["base_url"])
        names.add(name)
        channels.append(
            ImageProviderChannel(
                name=name,
                base_url=fields["base_url"],
                api_key=fields["api_key"],
                model=fields["model"],
                api_mode=mode,
            )
        )
    return tuple(channels)


class PooledCityBackgroundClient:
    """Thread-safe round-robin provider pool with per-process cooldowns."""

    def __init__(
        self,
        channels: tuple[tuple[ImageProviderChannel, CityBackgroundClient], ...],
        *,
        max_attempts: int = 2,
        cooldown_seconds: float = 600.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not channels:
            raise ValueError("image provider pool requires at least one channel")
        self._channels = channels
        self.max_attempts = min(
            _bounded_provider_attempts(max_attempts),
            len(channels),
        )
        self.cooldown_seconds = _positive_float(cooldown_seconds, 600.0)
        self._clock = clock
        self._lock = threading.Lock()
        self._next_start = 0
        self._cooldown_until: dict[str, float] = {}

    @property
    def channel_names(self) -> tuple[str, ...]:
        return tuple(channel.name for channel, _ in self._channels)

    def generate_background(self, prompt: str) -> GeneratedCityBackground:
        start = self._reserve_start()
        attempts: list[dict[str, Any]] = []
        for offset in range(len(self._channels)):
            if len(attempts) >= self.max_attempts:
                break
            channel, client = self._channels[(start + offset) % len(self._channels)]
            if self._is_cooling_down(channel.name):
                continue
            started = self._clock()
            try:
                generated = client.generate_background(prompt)
                image_bytes = (
                    generated.image_bytes
                    if isinstance(generated, GeneratedCityBackground)
                    else generated
                )
                open_image_bytes(image_bytes)
            except Exception as exc:
                elapsed_ms = _elapsed_ms(started, self._clock())
                error_code = _provider_error_code(exc)
                attempts.append(
                    _provider_attempt_metadata(
                        channel.name,
                        result="failed",
                        error_code=error_code,
                        elapsed_ms=elapsed_ms,
                    )
                )
                self._mark_cooldown(channel.name)
                continue

            attempts.append(
                _provider_attempt_metadata(
                    channel.name,
                    result="success",
                    error_code=None,
                    elapsed_ms=_elapsed_ms(started, self._clock()),
                )
            )
            return GeneratedCityBackground(
                image_bytes=image_bytes,
                metadata={
                    "ai_call_attempted": True,
                    "ai_call_count": len(attempts),
                    "provider_attempt_count": len(attempts),
                    "selected_provider_name": channel.name,
                    "provider_attempts": attempts,
                },
            )

        final_error_code = (
            str(attempts[-1]["error_code"])
            if attempts
            else "all_providers_cooling_down"
        )
        raise PooledBackgroundGenerationError(
            final_error_code,
            {
                "ai_call_attempted": bool(attempts),
                "ai_call_count": len(attempts),
                "provider_attempt_count": len(attempts),
                "provider_attempts": attempts,
                "background_error_code": final_error_code,
            },
        )

    def _reserve_start(self) -> int:
        with self._lock:
            start = self._next_start
            self._next_start = (self._next_start + 1) % len(self._channels)
            return start

    def _is_cooling_down(self, name: str) -> bool:
        now = self._clock()
        with self._lock:
            until = self._cooldown_until.get(name, 0.0)
            if until <= now:
                self._cooldown_until.pop(name, None)
                return False
            return True

    def _mark_cooldown(self, name: str) -> None:
        until = self._clock() + self.cooldown_seconds
        with self._lock:
            self._cooldown_until[name] = until


def _build_channel_client(
    channel: ImageProviderChannel,
    settings: Any,
) -> CityBackgroundClient:
    common = {
        "base_url": channel.base_url,
        "api_key": channel.api_key,
        "model": channel.model,
        "timeout_seconds": _positive_float(
            getattr(settings, "export_image_timeout_seconds", 360.0),
            360.0,
        ),
    }
    if channel.api_mode == "chat_completions":
        return OpenAIChatImageBackgroundClient(**common)
    return OpenAIImagesGenerationClient(
        **common,
        size=str(getattr(settings, "export_image_size", "1024x1536") or "1024x1536").strip(),
        quality=str(getattr(settings, "export_image_quality", "standard") or "standard").strip(),
        style=str(getattr(settings, "export_image_style", "vivid") or "vivid").strip(),
        response_format=str(
            getattr(settings, "export_image_response_format", "b64_json") or "b64_json"
        ).strip(),
    )


def _bounded_provider_attempts(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = IMAGE_PROVIDER_MAX_ATTEMPTS_HARD_LIMIT
    return max(1, min(parsed, IMAGE_PROVIDER_MAX_ATTEMPTS_HARD_LIMIT))


def _provider_error_code(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if isinstance(status_code, int):
        return f"HTTP_{status_code}"
    name = exc.__class__.__name__
    return name if re.fullmatch(r"[A-Za-z0-9_]{1,80}", name) else "ProviderError"


def _provider_attempt_metadata(
    provider_name: str,
    *,
    result: str,
    error_code: str | None,
    elapsed_ms: int,
) -> dict[str, Any]:
    return {
        "provider_name": provider_name,
        "result": result,
        "error_code": error_code,
        "elapsed_ms": elapsed_ms,
    }


def _elapsed_ms(started: float, finished: float) -> int:
    return max(0, int(round((finished - started) * 1000)))


@dataclass(frozen=True)
class CityBackground:
    image: Image.Image
    metadata: dict[str, Any]


def resolve_city_background(
    prompt: str,
    client: CityBackgroundClient | None,
) -> CityBackground:
    """Resolve a generated image or always return a usable packaged fallback."""

    fallback_key = fallback_city_key_from_prompt(prompt)
    if client is not None:
        started = time.monotonic()
        try:
            generated = client.generate_background(prompt)
            if isinstance(generated, GeneratedCityBackground):
                image_bytes = generated.image_bytes
                provider_metadata = dict(generated.metadata)
            else:
                image_bytes = generated
                provider_metadata = {
                    "ai_call_attempted": True,
                    "ai_call_count": 1,
                    "provider_attempt_count": 1,
                    "selected_provider_name": "legacy",
                    "provider_attempts": [
                        _provider_attempt_metadata(
                            "legacy",
                            result="success",
                            error_code=None,
                            elapsed_ms=_elapsed_ms(started, time.monotonic()),
                        )
                    ],
                }
            return CityBackground(
                image=open_image_bytes(image_bytes),
                metadata={
                    "background_status": "generated",
                    "background_byte_size": len(image_bytes),
                    **provider_metadata,
                },
            )
        except Exception as exc:
            image, fallback_metadata = fallback_city_background_with_metadata(fallback_key)
            if isinstance(exc, PooledBackgroundGenerationError):
                provider_metadata = dict(exc.metadata)
            else:
                error_code = _provider_error_code(exc)
                provider_metadata = {
                    "ai_call_attempted": True,
                    "ai_call_count": 1,
                    "provider_attempt_count": 1,
                    "provider_attempts": [
                        _provider_attempt_metadata(
                            "legacy",
                            result="failed",
                            error_code=error_code,
                            elapsed_ms=_elapsed_ms(started, time.monotonic()),
                        )
                    ],
                    "background_error_code": error_code,
                }
            return CityBackground(
                image=image,
                metadata={
                    "background_status": "fallback",
                    **provider_metadata,
                    **fallback_metadata,
                },
            )
    image, fallback_metadata = fallback_city_background_with_metadata(fallback_key)
    return CityBackground(
        image=image,
        metadata={
            "background_status": "fallback",
            "ai_call_attempted": False,
            "ai_call_count": 0,
            "provider_attempt_count": 0,
            "provider_attempts": [],
            "background_error_code": "not_configured",
            **fallback_metadata,
        },
    )


def open_image_bytes(data: bytes) -> Image.Image:
    if not data:
        raise ValueError("empty image")
    with Image.open(BytesIO(data)) as image:
        _validate_image_dimensions(image)
        return image.convert("RGB")


def fallback_city_background(
    fallback_key: str | None = None,
) -> Image.Image:
    return fallback_city_background_with_metadata(fallback_key)[0]


def fallback_city_background_with_metadata(
    fallback_key: str | None = None,
) -> tuple[Image.Image, dict[str, Any]]:
    normalized_key = _normalized_fallback_key(fallback_key)
    city_asset_path = _city_background_asset_path(normalized_key)
    if city_asset_path is not None:
        loaded = _load_background_asset(city_asset_path)
        if loaded is not None:
            return loaded, {
                "background_fallback_source": "packaged_city_asset",
                "background_fallback_key": normalized_key,
                "background_fallback_filename": city_asset_path.name,
            }

    loaded = _load_background_asset(FALLBACK_BACKGROUND_PATH)
    if loaded is not None:
        return loaded, {
            "background_fallback_source": "generic_fallback_asset",
            "background_fallback_key": "generic",
            "background_fallback_filename": FALLBACK_BACKGROUND_PATH.name,
        }

    return _generated_fallback_background(), {
        "background_fallback_source": "generated_generic_fallback",
        "background_fallback_key": "generic",
        "background_fallback_filename": None,
    }


def fallback_city_key_from_prompt(prompt: str) -> str | None:
    match = re.search(
        r"\bReference fallback city key:\s*([a-z0-9_-]+)\b",
        prompt or "",
        re.IGNORECASE,
    )
    if not match:
        return None
    return _normalized_fallback_key(match.group(1))


def message_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            item["text"]
            for item in content
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        )
    return ""


def extract_base64_image(content: str) -> bytes | None:
    match = re.search(
        r"data:image/(?:png|jpeg|jpg|webp);base64,([A-Za-z0-9+/=\s]+)",
        content or "",
        re.IGNORECASE,
    )
    if not match:
        return None
    raw = re.sub(r"\s+", "", match.group(1))
    try:
        return base64.b64decode(raw, validate=True)
    except Exception:
        return None


def first_image_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        raise ValueError("image response data is missing")
    return data[0]


def decode_base64_image(value: str) -> bytes:
    raw = re.sub(r"\s+", "", value or "")
    try:
        decoded = base64.b64decode(raw, validate=True)
    except Exception as exc:
        raise ValueError("image response b64_json is invalid") from exc
    if not decoded:
        raise ValueError("image response b64_json is empty")
    return decoded


def extract_markdown_image_url(content: str) -> str | None:
    match = re.search(r"!\[[^\]]*\]\((https?://[^\s)]+)\)", content or "", re.IGNORECASE)
    if not match:
        return None
    return match.group(1)


def _validate_http_url(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise ValueError("image URL must use http or https")
    if parsed.username or parsed.password:
        raise ValueError("image URL credentials are not allowed")


def _validate_http_image_url(
    value: str,
    *,
    dns_resolver: Callable[[str, int | None], list[str]],
) -> str:
    _validate_http_url(value)
    parsed = urlparse(value)
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("image URL hostname is missing")
    normalized_host = hostname.rstrip(".").lower()
    if normalized_host == "localhost" or normalized_host.endswith(".localhost"):
        raise ValueError("image URL localhost host is not allowed")
    if _is_ip_literal(normalized_host):
        if not _is_global_ip(normalized_host):
            raise ValueError("image URL IP address is not allowed")
        return value
    resolved_ips = dns_resolver(normalized_host, parsed.port)
    if not resolved_ips:
        raise ValueError("image URL hostname did not resolve")
    for resolved_ip in resolved_ips:
        if not _is_global_ip(resolved_ip):
            raise ValueError("image URL hostname resolved to a non-global IP")
    return value


def _is_ip_literal(hostname: str) -> bool:
    try:
        ipaddress.ip_address(hostname)
        return True
    except ValueError:
        return False


def _is_global_ip(value: str) -> bool:
    try:
        return ipaddress.ip_address(value).is_global
    except ValueError:
        return False


def _resolve_hostname_ips(hostname: str, port: int | None) -> list[str]:
    try:
        results = socket.getaddrinfo(
            hostname,
            port or 443,
            type=socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise ValueError("image URL hostname resolution failed") from exc
    addresses: list[str] = []
    for family, _, _, _, sockaddr in results:
        if family == socket.AF_INET:
            addresses.append(str(sockaddr[0]))
        elif family == socket.AF_INET6:
            addresses.append(str(sockaddr[0]))
    return list(dict.fromkeys(addresses))


def _validate_image_dimensions(image: Image.Image) -> None:
    width, height = image.size
    if width <= 0 or height <= 0:
        raise ValueError("image dimensions are invalid")
    if width > IMAGE_MAX_DIMENSION or height > IMAGE_MAX_DIMENSION:
        raise ValueError("image dimensions exceed the supported maximum")
    if width * height > IMAGE_MAX_PIXELS:
        raise ValueError("image pixel count exceeds the supported maximum")


def _generated_fallback_background() -> Image.Image:
    width, height = 1440, 2400
    image = Image.new("RGB", (width, height), "#E9EEE9")
    draw = ImageDraw.Draw(image)
    for y in range(height):
        ratio = y / max(1, height - 1)
        draw.line(
            (0, y, width, y),
            fill=(
                int(230 - 45 * ratio),
                int(238 - 28 * ratio),
                int(232 - 18 * ratio),
            ),
        )
    ridges = (
        ((0, 1370), (280, 1170), (570, 1360), (890, 1110), (1190, 1320), (1440, 1190)),
        ((0, 1700), (310, 1460), (640, 1640), (980, 1390), (1230, 1580), (1440, 1480)),
        ((0, 2020), (330, 1740), (680, 1940), (1040, 1670), (1280, 1880), (1440, 1800)),
    )
    for ridge, color in zip(ridges, ((155, 180, 168), (113, 153, 145), (68, 113, 108))):
        draw.polygon(list(ridge) + [(width, height), (0, height)], fill=color)
    return image.filter(ImageFilter.GaussianBlur(2.0))


def _positive_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _normalized_fallback_key(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().lower()
    if normalized in set(CITY_BACKGROUND_ASSET_KEYS.values()):
        return normalized
    return None


def _city_background_asset_path(fallback_key: str | None) -> Path | None:
    if not fallback_key:
        return None
    return CITY_BACKGROUND_ASSET_DIR / f"{fallback_key}.png"


def _load_background_asset(path: Path) -> Image.Image | None:
    try:
        return open_image_bytes(path.read_bytes())
    except Exception:
        return None
