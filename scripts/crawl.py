"""Crawl Xiaohongshu notes via TikHub and save travel_raw_item rows."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from src.pipeline.ingest import save_raw_item
from src.xhs.client import TikHubError, XhsClient
from src.xhs.filter import filter_and_rank

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("crawl")

MAX_SEARCH_PAGES = 8


async def _source_exists(source_id: str) -> bool:
    from sqlalchemy import text

    from src.pipeline.db import get_session_factory

    async with get_session_factory()() as session:
        row = (
            await session.execute(
                text(
                    """
                    SELECT 1
                    FROM travel_raw_item
                    WHERE source_platform = 'xhs'
                      AND source_type = 'note'
                      AND source_id = :source_id
                    LIMIT 1
                    """
                ),
                {"source_id": source_id},
            )
        ).first()
    return row is not None


async def crawl(
    *,
    city: str,
    keyword: str,
    limit: int,
    crawl_run_id: int | None,
) -> int:
    client = XhsClient()
    inserted = 0
    try:
        seen: set[str] = set()
        ranked = []
        search_id = None
        session_id = None
        raw_count = 0
        for page in range(1, MAX_SEARCH_PAGES + 1):
            page_result = await client.search_notes(
                keyword,
                page=page,
                search_id=search_id,
                search_session_id=session_id,
            )
            search_id = page_result.search_id or search_id
            session_id = page_result.search_session_id or session_id
            raw_count += len(page_result.items)
            print(f"Search returned {raw_count} items")
            for item in page_result.items:
                if item.note_id in seen or item.note_type == "video":
                    continue
                seen.add(item.note_id)
                ranked.append(item)
            ranked = filter_and_rank(ranked, city=city, top_n=max(limit * 3, limit))
            if len(filter_and_rank(ranked, city=city, top_n=limit)) >= limit:
                break
            if not page_result.items:
                break

        selected = filter_and_rank(ranked, city=city, top_n=limit)
        print(f"After filter: {len(selected)} notes pass")

        for item in selected:
            try:
                detail = await client.get_note_detail(item.note_id, note_type=item.note_type)
            except Exception as exc:
                print(f"Detail fetch failed note_id={item.note_id}: {exc}")
                logger.warning("detail failed note_id=%s error=%s", item.note_id, exc)
                continue
            existed = await _source_exists(detail.note_id)
            row_id = await save_raw_item(
                source_id=detail.note_id,
                city=city,
                keyword=keyword,
                raw_json=detail.raw,
                raw_text=detail.raw_text,
                source_url=detail.note_url,
                crawl_run_id=crawl_run_id,
                note_type=detail.note_type,
                author_id=detail.author_id,
                author_name=detail.author_name,
                author_url=detail.author_url,
                publish_time=detail.publish_time,
                image_urls=detail.image_urls,
                video_urls=detail.video_urls,
                cover_url=detail.cover_url,
                liked_count=detail.liked_count,
                collected_count=detail.collected_count,
                comment_count=detail.comment_count,
                shared_count=detail.shared_count,
                provider_request_id=detail.provider_request_id,
            )
            if existed or row_id is None:
                print(f"Skipped duplicate source_id={detail.note_id}")
            else:
                inserted += 1
                print(f"done: 1 inserted source_id={detail.note_id}")
        print(f"=== Crawl complete: {inserted} total raw items saved ===")
        return inserted
    finally:
        await client.close()


async def _run(args: argparse.Namespace) -> int:
    try:
        await crawl(
            city=args.city.strip(),
            keyword=args.keyword.strip(),
            limit=max(1, args.limit),
            crawl_run_id=args.crawl_run_id,
        )
        return 0
    except TikHubError as exc:
        print(str(exc.code).lower(), file=sys.stderr)
        print(str(exc), file=sys.stderr)
        logger.error("tikhub error code=%s msg=%s", exc.code, exc)
        return 1


def cli() -> None:
    parser = argparse.ArgumentParser(description="Crawl Xiaohongshu notes via TikHub")
    parser.add_argument("--city", required=True)
    parser.add_argument("--keyword", required=True)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--crawl-run-id", type=int, default=None)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    cli()