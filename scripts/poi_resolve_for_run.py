"""Resolve travel_place coordinates via Amap for one or more crawl runs."""

from __future__ import annotations

import argparse
import asyncio
import logging

from src.pipeline.poi_resolve import (
    AmapClient,
    fetch_place_resolution_targets,
    fetch_place_resolution_targets_for_runs,
    resolve_targets,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


async def _run(args: argparse.Namespace) -> int:
    run_ids = args.crawl_run_id or []
    client = AmapClient()
    try:
        if run_ids:
            targets = await fetch_place_resolution_targets_for_runs(
                run_ids,
                limit=max(1, args.limit),
                force=args.force,
            )
        elif args.city:
            targets = await fetch_place_resolution_targets(
                city=args.city.strip(),
                limit=max(1, args.limit),
                force=args.force,
            )
        else:
            print("No places to resolve")
            return 0
        if not targets:
            print("No places to resolve")
            return 0
        stats = await resolve_targets(targets, client=client)
        run_label = f" for crawl_run_ids={run_ids}" if run_ids else ""
        print(f"POI resolve done{run_label}: {stats}")
        return 0
    finally:
        await client.close()


def cli() -> None:
    parser = argparse.ArgumentParser(description="Resolve extracted places against Amap")
    parser.add_argument("--city", default="")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--crawl-run-id", type=int, action="append", default=[])
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    cli()