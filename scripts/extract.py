"""LLM-extract pending Xiaohongshu raw items into places and facts."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging

from src.pipeline.extract import call_llm_extract, fetch_pending_raw_items, save_extract_result

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("extract")


def _title(item: dict) -> str:
    raw = item.get("raw_json") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = {}
    if not isinstance(raw, dict):
        return ""
    data = raw.get("data") if isinstance(raw.get("data"), dict) else raw
    note = data.get("note_card") if isinstance(data.get("note_card"), dict) else data
    title = note.get("title") or note.get("display_title") or data.get("title") or ""
    return str(title).strip()


async def _run(args: argparse.Namespace) -> int:
    run_ids = args.crawl_run_id or None
    items = await fetch_pending_raw_items(limit=max(1, args.limit), crawl_run_ids=run_ids)
    print(f"Found {len(items)} pending raw items")
    success = 0
    failed = 0
    for item in items:
        city = item.get("city") or ""
        parsed, meta = await call_llm_extract(
            item.get("raw_text") or "",
            city,
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
    return 0


def cli() -> None:
    parser = argparse.ArgumentParser(description="Extract places from pending XHS raw items")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--crawl-run-id", type=int, action="append", default=[])
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    cli()