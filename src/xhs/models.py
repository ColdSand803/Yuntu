"""Provider-neutral Xiaohongshu note models and response normalization."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _first(mapping: dict, *keys: str, default=None):
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", [], {}):
            return value
    return default


def _as_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _as_time(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        number = int(value)
        if number > 10_000_000_000:
            number //= 1000
        return datetime.fromtimestamp(number, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        pass
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _urls(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        result: list[str] = []
        for key in (
            "url", "url_default", "url_size_large", "master_url",
            "backup_urls", "thumbnail", "first_frame",
        ):
            for url in _urls(value.get(key)):
                if url not in result:
                    result.append(url)
        for child in value.values():
            if isinstance(child, (dict, list)):
                for url in _urls(child):
                    if url not in result:
                        result.append(url)
        return result
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            for url in _urls(item):
                if url not in result:
                    result.append(url)
        return result
    return []


@dataclass(frozen=True)
class XhsSearchItem:
    note_id: str
    note_type: str
    title: str
    author_id: str | None
    author_name: str | None
    liked_count: int | None
    collected_count: int | None
    comment_count: int | None
    shared_count: int | None
    raw: dict


@dataclass(frozen=True)
class XhsSearchPage:
    items: list[XhsSearchItem]
    search_id: str | None = None
    search_session_id: str | None = None
    provider_request_id: str | None = None
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True)
class NormalizedXhsNote:
    note_id: str
    note_type: str
    title: str
    description: str
    author_id: str | None
    author_name: str | None
    author_url: str | None
    publish_time: datetime | None
    liked_count: int | None
    collected_count: int | None
    comment_count: int | None
    shared_count: int | None
    note_url: str
    image_urls: list[str]
    video_urls: list[str]
    cover_url: str | None
    provider_request_id: str | None
    raw: dict

    @property
    def raw_text(self) -> str:
        return "\n\n".join(
            part.strip() for part in (self.title, self.description) if part.strip()
        )


def _payload_data(payload: dict) -> dict:
    data = payload.get("data")
    if isinstance(data, dict):
        return data
    return payload


def _item_list(data: Any) -> list[dict]:
    if isinstance(data, list):
        for item in data:
            found = _item_list(item)
            if found:
                return found
        return [item for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        return []
    for key in ("items", "notes", "note_list", "feeds", "list"):
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    nested = data.get("data")
    if isinstance(nested, (dict, list)):
        return _item_list(nested)
    return []


def normalize_search_page(payload: dict) -> XhsSearchPage:
    data = _payload_data(payload)
    items: list[XhsSearchItem] = []
    for raw in _item_list(data):
        if isinstance(raw.get("note"), dict):
            note = raw["note"]
        elif isinstance(raw.get("note_card"), dict):
            note = raw["note_card"]
        else:
            note = raw
        user = note.get("user") if isinstance(note.get("user"), dict) else {}
        interact = (
            note.get("interact_info")
            if isinstance(note.get("interact_info"), dict)
            else {}
        )
        note_id = str(_first(raw, "id", "note_id", default=_first(note, "id", "note_id", default="")))
        if not note_id:
            continue
        note_type = str(_first(note, "type", "note_type", default="image")).lower()
        if "video" in note_type:
            note_type = "video"
        else:
            note_type = "image"
        items.append(XhsSearchItem(
            note_id=note_id,
            note_type=note_type,
            title=str(_first(note, "title", "display_title", "name", default="")),
            author_id=str(_first(user, "user_id", "userid", "id", default="")) or None,
            author_name=str(_first(user, "nickname", "name", default="")) or None,
            liked_count=_as_int(_first(
                interact, "liked_count", "likes", "liked",
                default=_first(note, "liked_count", "nice_count"),
            )),
            collected_count=_as_int(_first(
                interact, "collected_count", "collects", "collected",
                default=_first(note, "collected_count"),
            )),
            comment_count=_as_int(_first(
                interact, "comment_count", "comments",
                default=_first(note, "comments_count", "comment_count"),
            )),
            shared_count=_as_int(_first(
                interact, "shared_count", "shares",
                default=_first(note, "shared_count"),
            )),
            raw=raw,
        ))
    return XhsSearchPage(
        items=items,
        search_id=str(_first(data, "search_id", default="")) or None,
        search_session_id=str(_first(data, "search_session_id", "session_id", default="")) or None,
        provider_request_id=str(_first(payload, "request_id", "trace_id", default="")) or None,
        raw=payload,
    )


def normalize_note_detail(
    payload: dict,
    *,
    note_id: str,
    note_type: str,
) -> NormalizedXhsNote:
    data = _payload_data(payload)
    candidates = _item_list(data)
    note = candidates[0] if candidates else data
    if isinstance(note.get("note_card"), dict):
        note = note["note_card"]
    user = note.get("user") if isinstance(note.get("user"), dict) else {}
    interact = (
        note.get("interact_info")
        if isinstance(note.get("interact_info"), dict)
        else {}
    )
    images = _first(note, "image_list", "images_list", "images", default=[])
    video = _first(note, "video_info_v2", "video", "video_info", default={})
    media = _first(video, "media", default=video)
    video_urls = _urls(_first(media, "stream", "url", "master_url", default=media))
    cover_urls = _urls(_first(
        video, "image", "cover", "cover_url", default=None
    ))
    author_id = str(_first(user, "user_id", "userid", "id", default="")) or None
    return NormalizedXhsNote(
        note_id=note_id,
        note_type=note_type,
        title=str(_first(note, "title", "display_title", default="")),
        description=str(_first(note, "desc", "description", "content", default="")),
        author_id=author_id,
        author_name=str(_first(user, "nickname", "name", default="")) or None,
        author_url=(
            f"https://www.xiaohongshu.com/user/profile/{author_id}"
            if author_id else None
        ),
        publish_time=_as_time(_first(note, "time", "publish_time", "create_time")),
        liked_count=_as_int(_first(
            interact, "liked_count", "likes", "liked",
            default=_first(note, "liked_count", "nice_count"),
        )),
        collected_count=_as_int(_first(
            interact, "collected_count", "collects", "collected",
            default=_first(note, "collected_count"),
        )),
        comment_count=_as_int(_first(
            interact, "comment_count", "comments",
            default=_first(note, "comments_count", "comment_count"),
        )),
        shared_count=_as_int(_first(
            interact, "shared_count", "shares",
            default=_first(note, "shared_count"),
        )),
        note_url=f"https://www.xiaohongshu.com/explore/{note_id}",
        image_urls=_urls(images),
        video_urls=video_urls,
        cover_url=(cover_urls[0] if cover_urls else None),
        provider_request_id=str(_first(payload, "request_id", "trace_id", default="")) or None,
        raw=payload,
    )
