"""Refresh travel_place_summary aggregates after extract/POI resolve."""

from __future__ import annotations

import argparse
import asyncio
import logging

from src.pipeline.refresh import refresh_place_summary

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


async def _run(args: argparse.Namespace) -> int:
    total = await refresh_place_summary(args.city.strip() if args.city else None)
    print(f"Done. {int(total or 0)} summaries refreshed")
    return 0


def cli() -> None:
    parser = argparse.ArgumentParser(description="Refresh place summary scores")
    parser.add_argument("--city", default="")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    cli()