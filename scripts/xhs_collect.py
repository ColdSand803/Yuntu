"""One-city Xiaohongshu collect: crawl -> extract -> POI resolve -> summary -> onboard."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from src.jobs.city_keywords import city_batch_keywords
from src.jobs.city_store import get_or_create_city
from src.jobs.crawl_store import create_crawl_run
from src.pipeline.canonical_onboarding import onboard_city
from src.pipeline.extract import call_llm_extract, fetch_pending_raw_items, save_extract_result
from src.pipeline.poi_resolve import (
    AmapClient,
    fetch_place_resolution_targets_for_runs,
    resolve_targets,
)
from src.pipeline.refresh import refresh_place_summary
from src.xhs.client import TikHubError

from scripts.crawl import crawl
from scripts.extract import _title

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("xhs_collect")


async def _run(args: argparse.Namespace) -> int:
    city = args.city.strip()
    await get_or_create_city(city)
    keywords = [args.keyword.strip()] if args.keyword else [item[0] for item in city_batch_keywords(city)]
    if args.max_keywords:
        keywords = keywords[: max(1, args.max_keywords)]
    run_ids: list[int] = []
    try:
        for keyword in keywords:
            run_id = await create_crawl_run(
                city=city,
                keyword=keyword,
                limit=args.limit,
                run_extract=False,
                refresh_summary=False,
                trigger_source="manual",
            )
            print(f"crawl keyword={keyword} run_id={run_id}")
            await crawl(
                city=city,
                keyword=keyword,
                limit=args.limit,
                crawl_run_id=run_id,
            )
            run_ids.append(run_id)
    except TikHubError as exc:
        print(str(exc.code).lower(), file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 1

    items = await fetch_pending_raw_items(
        limit=max(1, args.limit * max(1, len(run_ids))),
        crawl_run_ids=run_ids,
    )
    print(f"Found {len(items)} pending raw items")
    success = failed = 0
    for item in items:
        parsed, meta = await call_llm_extract(
            item.get("raw_text") or "",
            item.get("city") or city,
            title=_title(item),
        )
        await save_extract_result(item, parsed, meta)
        places = parsed.get("places") if isinstance(parsed, dict) else None
        if isinstance(places, list) and any(
            isinstance(p, dict) and str(p.get("name") or "").strip() for p in places
        ):
            success += 1
        else:
            failed += 1
    print(
        f"=== Extract complete: {success} success (with places), {failed} failed/partial ==="
    )

    client = AmapClient()
    try:
        targets = await fetch_place_resolution_targets_for_runs(
            run_ids,
            limit=500,
        )
        if targets:
            stats = await resolve_targets(targets, client=client)
            print(f"POI resolve done for crawl_run_ids={run_ids}: {stats}")
        else:
            print("No places to resolve")
    finally:
        await client.close()

    total = await refresh_place_summary(city)
    print(f"Done. {int(total or 0)} summaries refreshed")
    onboard = await onboard_city(city, crawl_run_ids=run_ids)
    print(
        "canonical onboard "
        f"scanned={onboard.scanned} created={onboard.created} linked={onboard.linked} "
        f"auto_accepted={onboard.auto_accepted} pending_review={onboard.pending_review}"
    )
    return 0


def cli() -> None:
    parser = argparse.ArgumentParser(description="Collect one city from Xiaohongshu via TikHub")
    parser.add_argument("--city", required=True)
    parser.add_argument("--keyword", default="", help="Single keyword; default uses city batch keywords")
    parser.add_argument("--limit", type=int, default=10, help="Notes per keyword after filter")
    parser.add_argument("--max-keywords", type=int, default=3)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    cli()