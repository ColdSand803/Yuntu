"""Promote resolved discovered places into travel_canonical_place."""

from __future__ import annotations

import argparse
import asyncio
import logging

from src.pipeline.canonical_onboarding import onboard_city

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


async def _run(args: argparse.Namespace) -> int:
    stats = await onboard_city(
        args.city.strip(),
        crawl_run_ids=args.crawl_run_id or None,
    )
    print(
        "canonical onboard "
        f"scanned={stats.scanned} created={stats.created} linked={stats.linked} "
        f"auto_accepted={stats.auto_accepted} pending_review={stats.pending_review}"
    )
    return 0


def cli() -> None:
    parser = argparse.ArgumentParser(description="Onboard resolved XHS places to canonical POIs")
    parser.add_argument("--city", required=True)
    parser.add_argument("--crawl-run-id", type=int, action="append", default=[])
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    cli()