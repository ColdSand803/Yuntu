"""Parse subprocess stdout/stderr into crawl step metrics."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class StepMetrics:
    raw_count: int = 0
    insert_count: int = 0
    duplicate_count: int = 0
    failed_count: int = 0


def parse_step_metrics(step_name: str, stdout: str, stderr: str) -> StepMetrics:
    text = f"{stdout}\n{stderr}"

    if step_name == "CRAWL":
        raw_count = 0
        insert_count = 0
        for pattern in (
            r"Search returned (\d+) items",
            r"After filter: (\d+) notes pass",
        ):
            match = re.search(pattern, text)
            if match:
                raw_count = max(raw_count, int(match.group(1)))

        complete_match = re.search(
            r"=== Crawl complete: (\d+) total raw items saved ===",
            text,
        )
        if complete_match:
            insert_count = int(complete_match.group(1))
        else:
            done_matches = re.findall(r"done: (\d+) inserted", text)
            if done_matches:
                insert_count = sum(int(value) for value in done_matches)

        duplicate_count = len(re.findall(r"Skipped duplicate source_id=", text))
        failed_count = len(re.findall(r"Detail fetch failed", text))
        return StepMetrics(
            raw_count=raw_count,
            insert_count=insert_count,
            duplicate_count=duplicate_count,
            failed_count=failed_count,
        )

    if step_name == "EXTRACT":
        raw_count = 0
        insert_count = 0
        failed_count = 0
        found_match = re.search(r"Found (\d+) pending raw items", text)
        if found_match:
            raw_count = int(found_match.group(1))
        summary_match = re.search(
            r"=== Extract complete: (\d+) success \(with places\), (\d+) failed/partial ===",
            text,
        )
        if summary_match:
            insert_count = int(summary_match.group(1))
            failed_count = int(summary_match.group(2))
        return StepMetrics(
            raw_count=raw_count,
            insert_count=insert_count,
            failed_count=failed_count,
        )

    if step_name == "REFRESH_SUMMARY":
        refresh_match = re.search(r"Done\. (\d+) summaries refreshed", text)
        insert_count = int(refresh_match.group(1)) if refresh_match else 0
        return StepMetrics(insert_count=insert_count)

    if step_name == "POI_RESOLVE":
        done_match = re.search(
            r"POI resolve done(?: for crawl_run_ids=\[[^\]]*\])?: "
            r"\{'resolved': (\d+), 'unresolvable': (\d+), 'pending': (\d+)\}",
            text,
        )
        if done_match:
            resolved = int(done_match.group(1))
            unresolvable = int(done_match.group(2))
            pending = int(done_match.group(3))
            return StepMetrics(
                raw_count=resolved + unresolvable + pending,
                insert_count=resolved,
                failed_count=unresolvable,
            )
        if re.search(r"No places to resolve", text):
            return StepMetrics()

    return StepMetrics()
