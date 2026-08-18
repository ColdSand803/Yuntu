"""Batch stress test: run trip workflow with 5 different user inputs sequentially."""

from __future__ import annotations

import asyncio
import logging
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

TEST_QUERIES = [
    "重庆3天 不想太累 喜欢美食和citywalk",
    "重庆2天 喜欢拍照打卡 想去网红地",
    "重庆4天 看夜景 喜欢江景",
    "带小孩去重庆 3天 亲子 轻松一点",
    "一个人去重庆 2天 citywalk 不要人太多的地方",
]


def _check_result(query: str, result) -> list[str]:
    """Return list of issues found, empty means pass."""
    issues = []
    if not result.plans:
        issues.append("NO PLANS generated")
        return issues
    recommendation_scope = (result.quality_metrics or {}).get(
        "recommendation_scope",
        {},
    )
    expected_plan_count = max(
        1,
        int(recommendation_scope.get("target_plan_count", 2)),
    )
    if len(result.plans) < expected_plan_count:
        issues.append(
            f"Only {len(result.plans)} plan(s), expected {expected_plan_count}"
        )
    for plan in result.plans:
        if len(plan.used_place_names) < 5:
            issues.append(
                f"Plan '{plan.plan_name}': only {len(plan.used_place_names)} places, need ≥5"
            )
        dupes = [n for n in set(plan.used_place_names)
                 if plan.used_place_names.count(n) > 1]
        if dupes:
            issues.append(f"Plan '{plan.plan_name}': duplicate places {dupes}")
    return issues


async def main() -> None:
    from src.agents.workflow import run_trip_workflow

    results_summary = []

    for i, query in enumerate(TEST_QUERIES, 1):
        print(f"\n{'='*60}")
        print(f"[{i}/{len(TEST_QUERIES)}] {query}")
        print("=" * 60)

        t0 = time.monotonic()
        try:
            result = await run_trip_workflow(query)
            elapsed = time.monotonic() - t0
            issues = _check_result(query, result)

            status = "PASS" if not issues else "WARN"
            results_summary.append({
                "query": query,
                "status": status,
                "elapsed": elapsed,
                "plans": len(result.plans),
                "issues": issues,
                "to_city": result.trip_request.to_city,
                "days": result.trip_request.days,
                "preferences": result.trip_request.preferences,
            })

            for plan in result.plans:
                print(f"\n  方案: {plan.plan_name}")
                print(f"  地点({len(plan.used_place_names)}): {', '.join(plan.used_place_names)}")

            print(f"\n  审核: {result.review_notes[:120]}")
            print(f"  耗时: {elapsed:.1f}s  状态: {status}")
            if issues:
                for issue in issues:
                    print(f"  WARN {issue}")

        except Exception as e:
            elapsed = time.monotonic() - t0
            results_summary.append({
                "query": query,
                "status": "FAIL",
                "elapsed": elapsed,
                "plans": 0,
                "issues": [str(e)],
            })
            print(f"  FAIL ({elapsed:.1f}s): {e}")

        # avoid hammering the API back-to-back
        if i < len(TEST_QUERIES):
            await asyncio.sleep(3)

    print(f"\n{'='*60}")
    print("压测汇总")
    print("=" * 60)
    pass_count = sum(1 for r in results_summary if r["status"] == "PASS")
    warn_count = sum(1 for r in results_summary if r["status"] == "WARN")
    fail_count = sum(1 for r in results_summary if r["status"] == "FAIL")
    total_time = sum(r["elapsed"] for r in results_summary)

    print(f"PASS: {pass_count}  WARN: {warn_count}  FAIL: {fail_count}  "
          f"总耗时: {total_time:.0f}s")
    print()
    for r in results_summary:
        flag = {"PASS": "PASS", "WARN": "WARN", "FAIL": "FAIL"}[r["status"]]
        prefs = r.get("preferences", [])
        print(f"  {flag} [{r['elapsed']:5.1f}s] {r['query'][:40]:<40}"
              f"  plans={r['plans']}  偏好={prefs}")
        for issue in r.get("issues", []):
            print(f"        WARN {issue}")


if __name__ == "__main__":
    asyncio.run(main())
