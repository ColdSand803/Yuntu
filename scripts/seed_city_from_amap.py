"""Seed travel_canonical_place for one or more cities from Amap POI search."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from src.config import get_settings
from src.pipeline.canonical_amap_import import ImportConfig, ImportStats, import_city
from src.pipeline.poi_resolve import AmapClient, AmapDefinitiveNotFound, AmapTransientError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("seed_city_from_amap")


def _parse_cities(raw: str) -> list[str]:
    cities: list[str] = []
    for part in raw.replace("，", ",").split(","):
        name = part.strip()
        if name and name not in cities:
            cities.append(name)
    if not cities:
        raise ValueError("at least one city is required")
    return cities


def _print_preview(stats: ImportStats, *, limit: int = 30) -> None:
    print(f"\n[{stats.city}] scanned={stats.scanned} prepared={stats.prepared}")
    print(
        "  skipped: "
        f"junk={stats.skipped_junk} rating={stats.skipped_rating} "
        f"city={stats.skipped_city} dup={stats.skipped_dup}"
    )
    print(
        f"  {'type':<20} {'pri':>3} {'rating':>6}  name"
    )
    for place in stats.preview[:limit]:
        rating = f"{place.rating:.1f}" if place.rating is not None else "-"
        print(
            f"  {place.mapped.place_type:<20} {place.mapped.base_priority:>3} "
            f"{rating:>6}  {place.canonical_name}"
        )
    remaining = len(stats.preview) - limit
    if remaining > 0:
        print(f"  ... {remaining} more")


def _print_result(stats: ImportStats) -> None:
    _print_preview(stats)
    print(
        f"  wrote: inserted={stats.inserted} updated={stats.updated} "
        f"protected={stats.protected} status={stats.city_status}"
    )
    if stats.quality is not None:
        print(
            "  quality: "
            f"activity={stats.quality.route_eligible_activity_count} "
            f"food={stats.quality.route_eligible_food_count} "
            f"types={stats.quality.route_eligible_type_coverage} "
            f"canonical_pass={stats.quality.canonical_quality_pass} "
            f"gray={stats.quality.gray_eligible}"
        )
        if not stats.quality.gray_eligible:
            print("  warning: POI count is below GRAY threshold; planning may still fail.")


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    if not (settings.amap_api_key or settings.amap_api_key_two):
        print("AMAP_API_KEY is not configured. Set it in .env and retry.", file=sys.stderr)
        return 2

    config = ImportConfig(
        dry_run=args.dry_run,
        activate=args.activate,
        max_attractions=args.max_attractions,
        max_food=args.max_food,
        max_areas=args.max_areas,
        min_food_rating=args.min_food_rating,
        max_pages=args.pages,
    )
    cities = _parse_cities(args.city)
    client = AmapClient()
    exit_code = 0
    try:
        for city in cities:
            logger.info("importing city=%s dry_run=%s activate=%s", city, config.dry_run, config.activate)
            try:
                stats = await import_city(city, client=client, config=config)
            except (AmapTransientError, AmapDefinitiveNotFound) as exc:
                print(f"Amap request failed for {city}: {exc}", file=sys.stderr)
                print(
                    "Check AMAP_API_KEY is a Web service key with 搜索/地理编码 enabled.",
                    file=sys.stderr,
                )
                return 2
            if config.dry_run:
                _print_preview(stats)
            else:
                _print_result(stats)
            if stats.prepared == 0:
                exit_code = 1
    finally:
        await client.close()
    return exit_code


def cli() -> None:
    parser = argparse.ArgumentParser(
        description="Import canonical city POIs from Amap place search",
    )
    parser.add_argument(
        "--city",
        required=True,
        help="City name, comma-separated for multiple (e.g. 成都 or 成都,杭州)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Search and print, do not write DB")
    parser.add_argument(
        "--activate",
        action="store_true",
        help="Force travel_city.status=ACTIVE after import (self-host)",
    )
    parser.add_argument("--max-attractions", type=int, default=45)
    parser.add_argument("--max-food", type=int, default=20)
    parser.add_argument("--max-areas", type=int, default=8)
    parser.add_argument("--min-food-rating", type=float, default=4.3)
    parser.add_argument("--pages", type=int, default=4, help="Max Amap pages per search group (offset=25)")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    cli()