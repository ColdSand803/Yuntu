"""End-to-end test: run the full trip workflow from a natural language query."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


async def main(query: str) -> None:
    from src.agents.workflow import run_trip_workflow

    result = await run_trip_workflow(query)

    print("\n" + "=" * 60)
    print(f"目的地: {result.trip_request.to_city}  天数: {result.trip_request.days}")
    print(f"偏好: {result.trip_request.preferences}")
    print(f"避开: {result.trip_request.avoid}")
    print("=" * 60)

    for i, plan in enumerate(result.plans, 1):
        print(f"\n{'─' * 40}")
        print(f"方案 {i}: {plan.plan_name}")
        print(f"使用地点 ({len(plan.used_place_names)}): {', '.join(plan.used_place_names)}")
        print(f"{'─' * 40}")
        print(plan.plan_text)

    if result.review_notes:
        print(f"\n{'─' * 40}")
        print("审核意见:")
        print(result.review_notes)

    print("\n[OK] travel_plan_record 已落库")


def cli() -> None:
    parser = argparse.ArgumentParser(description="Run trip workflow end-to-end")
    parser.add_argument(
        "query",
        nargs="?",
        default="重庆3天 不想太累 喜欢美食和citywalk",
        help="Natural language trip query",
    )
    args = parser.parse_args()
    asyncio.run(main(args.query))


if __name__ == "__main__":
    cli()
