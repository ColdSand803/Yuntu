"""Raw item ingestion: save XHS search results and note details to travel_raw_item."""

from __future__ import annotations

import hashlib
import json
import logging

from sqlalchemy import text

from src.pipeline.db import get_session_factory

logger = logging.getLogger(__name__)


def _content_hash(raw_json: dict) -> str:
    """Deterministic SHA-256 over the raw JSON payload."""
    blob = json.dumps(raw_json, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


async def save_raw_item(
    *,
    source_id: str,
    city: str,
    keyword: str,
    raw_json: dict,
    raw_text: str,
    source_url: str = "",
    crawl_task_id: int | None = None,
    crawl_run_id: int | None = None,
    raw_status: str = "NORMAL",
    provider: str = "tikhub",
    provider_request_id: str | None = None,
    note_type: str | None = None,
    author_id: str | None = None,
    author_name: str | None = None,
    author_url: str | None = None,
    publish_time=None,
    image_urls: list[str] | None = None,
    video_urls: list[str] | None = None,
    cover_url: str | None = None,
    liked_count: int | None = None,
    collected_count: int | None = None,
    comment_count: int | None = None,
    shared_count: int | None = None,
) -> int | None:
    """Insert or skip (on conflict) a single raw item. Returns the row id or None if skipped."""
    factory = get_session_factory()
    content_hash = _content_hash(raw_json)

    async with factory() as session:
        result = await session.execute(
            text("""
                INSERT INTO travel_raw_item
                    (source_platform, source_type, source_id, source_url,
                     city, keyword, raw_json, raw_text, content_hash,
                     crawl_task_id, crawl_run_id, raw_status,
                     provider, provider_request_id, note_type,
                     author_id, author_name, author_url, publish_time,
                     image_urls, video_urls, cover_url,
                     liked_count, collected_count, comment_count, shared_count)
                VALUES
                    (:platform, :stype, :source_id, :source_url,
                     :city, :keyword, CAST(:raw_json AS jsonb), :raw_text, :content_hash,
                     :crawl_task_id, :crawl_run_id, :raw_status,
                     :provider, :provider_request_id, :note_type,
                     :author_id, :author_name, :author_url, :publish_time,
                     CAST(:image_urls AS jsonb), CAST(:video_urls AS jsonb), :cover_url,
                     :liked_count, :collected_count, :comment_count, :shared_count)
                ON CONFLICT (source_platform, source_type, source_id)
                    WHERE source_id IS NOT NULL
                DO UPDATE SET
                    raw_json = CAST(:raw_json AS jsonb),
                    raw_text = CASE WHEN :raw_status = 'NORMAL'
                        THEN :raw_text ELSE travel_raw_item.raw_text END,
                    content_hash = :content_hash,
                    source_url = :source_url,
                    crawl_run_id = :crawl_run_id,
                    provider = :provider,
                    provider_request_id = :provider_request_id,
                    note_type = :note_type,
                    author_id = COALESCE(:author_id, travel_raw_item.author_id),
                    author_name = COALESCE(:author_name, travel_raw_item.author_name),
                    author_url = COALESCE(:author_url, travel_raw_item.author_url),
                    publish_time = COALESCE(:publish_time, travel_raw_item.publish_time),
                    image_urls = CAST(:image_urls AS jsonb),
                    video_urls = CAST(:video_urls AS jsonb),
                    cover_url = COALESCE(:cover_url, travel_raw_item.cover_url),
                    liked_count = :liked_count,
                    collected_count = :collected_count,
                    comment_count = :comment_count,
                    shared_count = :shared_count,
                    raw_status = CASE
                        WHEN :raw_status = 'NORMAL' THEN 'NORMAL'
                        ELSE travel_raw_item.raw_status
                    END,
                    parse_status = CASE
                        WHEN travel_raw_item.content_hash IS DISTINCT FROM :content_hash
                             AND :raw_status = 'NORMAL' THEN 'PENDING'
                        ELSE travel_raw_item.parse_status
                    END
                RETURNING id
            """),
            {
                "platform": "xhs",
                "stype": "note",
                "source_id": source_id,
                "source_url": source_url,
                "city": city,
                "keyword": keyword,
                "raw_json": json.dumps(raw_json, ensure_ascii=False),
                "raw_text": raw_text,
                "content_hash": content_hash,
                "crawl_task_id": crawl_task_id,
                "crawl_run_id": crawl_run_id,
                "raw_status": raw_status,
                "provider": provider,
                "provider_request_id": provider_request_id,
                "note_type": note_type,
                "author_id": author_id,
                "author_name": author_name,
                "author_url": author_url,
                "publish_time": publish_time,
                "image_urls": json.dumps(image_urls or [], ensure_ascii=False),
                "video_urls": json.dumps(video_urls or [], ensure_ascii=False),
                "cover_url": cover_url,
                "liked_count": liked_count,
                "collected_count": collected_count,
                "comment_count": comment_count,
                "shared_count": shared_count,
            },
        )
        await session.commit()
        row = result.fetchone()
        if row:
            logger.info("Saved raw_item id=%s source_id=%s", row[0], source_id)
            return row[0]
        logger.info("Skipped duplicate source_id=%s", source_id)
        return None


async def update_raw_status(raw_item_id: int, status: str, parse_error: str = ""):
    """Update raw_status or parse_status for error handling."""
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("""
                UPDATE travel_raw_item
                SET raw_status = :status, parse_error = :error
                WHERE id = :id
            """),
            {"status": status, "id": raw_item_id, "error": parse_error},
        )
        await session.commit()


async def update_crawl_task_status(
    city: str, keyword: str, status: str, fail_reason: str = ""
):
    """Upsert crawl_task record with latest result status."""
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("""
                INSERT INTO travel_crawl_task
                    (city, keyword, source_platform, source_type,
                     last_result_status, last_run_time, fail_reason)
                VALUES
                    (:city, :keyword, 'xhs', 'note',
                     :status, NOW(), :fail_reason)
                ON CONFLICT (city, keyword, source_platform, source_type)
                DO UPDATE SET
                    last_result_status = :status,
                    last_run_time = NOW(),
                    fail_reason = :fail_reason,
                    fail_count = CASE
                        WHEN :status IN ('SUCCESS') THEN 0
                        ELSE travel_crawl_task.fail_count + 1
                    END,
                    last_success_time = CASE
                        WHEN :status = 'SUCCESS' THEN NOW()
                        ELSE travel_crawl_task.last_success_time
                    END
            """),
            {
                "city": city,
                "keyword": keyword,
                "status": status,
                "fail_reason": fail_reason,
            },
        )
        await session.commit()
