"""Deterministic city quality inspection for v0.6.15 city foundation."""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.pipeline.db import get_session_factory

CANONICAL_MIN_ACTIVITY_COUNT = 25
CANONICAL_MIN_FOOD_COUNT = 10
CANONICAL_MIN_TYPE_COVERAGE = 4
CANONICAL_MIN_GEO_RATIO = 0.8
EVIDENCE_MIN_EFFECTIVE_PLACES = 20
EVIDENCE_MIN_EFFECTIVE_EVIDENCE = 20
EVIDENCE_MIN_TYPE_COVERAGE = 4

_FOOD_PLACE_TYPES = ("restaurant", "food", "cafe", "snack", "snack_shop", "dessert", "market")

_QUALITY_METRICS_SQL = """
WITH canonical_scope AS (
    SELECT *
    FROM travel_canonical_place
    WHERE city = :city
      AND trust_level = 'trusted'
      AND review_status IN ('reviewed', 'auto_accepted')
      AND is_active = TRUE
),
route_eligible AS (
    SELECT *
    FROM canonical_scope
    WHERE geo_status IN ('resolved', 'coordinate_only')
      AND latitude IS NOT NULL
      AND longitude IS NOT NULL
),
canonical_coverage AS (
    SELECT DISTINCT
        CASE
            WHEN place_type = ANY(CAST(:food_place_types AS text[])) THEN 'food'
            ELSE place_type
        END AS coverage_type
    FROM route_eligible
),
summary_scope AS (
    SELECT
        s.canonical_place_id,
        c.place_type,
        COALESCE(s.source_count, 0) AS source_count
    FROM travel_place_summary AS s
    JOIN canonical_scope AS c
      ON c.place_id = s.canonical_place_id
    WHERE s.canonical_place_id IS NOT NULL
      AND s.source_count >= 1
      AND s.quality_score >= 1.5
),
summary_coverage AS (
    SELECT DISTINCT
        CASE
            WHEN place_type = ANY(CAST(:food_place_types AS text[])) THEN 'food'
            ELSE place_type
        END AS coverage_type
    FROM summary_scope
)
SELECT
    (SELECT COUNT(*)::int FROM route_eligible
     WHERE place_type <> ALL(CAST(:food_place_types AS text[]))) AS route_eligible_activity_count,
    (SELECT COUNT(*)::int FROM route_eligible
     WHERE place_type = ANY(CAST(:food_place_types AS text[]))) AS route_eligible_food_count,
    (SELECT COUNT(*)::int FROM canonical_coverage) AS route_eligible_type_coverage,
    COALESCE(
        (SELECT COUNT(*)::numeric FROM route_eligible)
        / NULLIF((SELECT COUNT(*)::numeric FROM canonical_scope), 0),
        0
    ) AS canonical_geo_resolved_ratio,
    (SELECT COUNT(DISTINCT canonical_place_id)::int FROM summary_scope) AS summary_effective_places,
    (SELECT COALESCE(SUM(source_count), 0)::int FROM summary_scope) AS summary_effective_evidence,
    (SELECT COUNT(*)::int FROM summary_coverage) AS summary_type_coverage
"""


_BASE_SNAPSHOT_COLUMNS = (
    ("city_id", ":city_id"),
    ("valid_place_count", ":valid_place_count"),
    ("valid_evidence_count", ":valid_evidence_count"),
    ("covered_categories", "CAST(:covered_categories AS jsonb)"),
    ("successful_base_keywords", "CAST(:successful_base_keywords AS jsonb)"),
    ("blocking_issues", "CAST(:blocking_issues AS jsonb)"),
    ("gray_eligible", ":gray_eligible"),
    ("active_eligible", ":active_eligible"),
)

_V0615_SNAPSHOT_COLUMNS = (
    ("canonical_route_eligible_activity_count", ":route_eligible_activity_count"),
    ("canonical_route_eligible_food_count", ":route_eligible_food_count"),
    ("canonical_route_eligible_type_coverage", ":route_eligible_type_coverage"),
    ("canonical_geo_resolved_ratio", ":canonical_geo_resolved_ratio"),
    ("canonical_quality_pass", ":canonical_quality_pass"),
    ("summary_effective_places", ":summary_effective_places"),
    ("summary_effective_evidence", ":summary_effective_evidence"),
    ("summary_type_coverage", ":summary_type_coverage"),
    ("evidence_quality_pass", ":evidence_quality_pass"),
)


@dataclass(frozen=True)
class CityQualityMetrics:
    valid_place_count: int
    valid_evidence_count: int
    covered_categories: tuple[str, ...]
    successful_base_keywords: tuple[str, ...]
    blocking_issues: tuple[str, ...]
    gray_eligible: bool
    active_eligible: bool
    route_eligible_activity_count: int = 0
    route_eligible_food_count: int = 0
    route_eligible_type_coverage: int = 0
    canonical_geo_resolved_ratio: float = 0.0
    canonical_quality_pass: bool | None = None
    summary_effective_places: int = 0
    summary_effective_evidence: int = 0
    summary_type_coverage: int = 0
    evidence_quality_pass: bool | None = None


async def _has_city_foundation_schema(session: AsyncSession) -> bool:
    row = (await session.execute(text("""
        SELECT
            to_regclass('travel_canonical_place') IS NOT NULL AS has_canonical_table,
            EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'travel_place_summary'
                  AND column_name = 'canonical_place_id'
            ) AS has_summary_link
    """))).one()
    return bool(row.has_canonical_table and row.has_summary_link)


async def _snapshot_columns(session: AsyncSession) -> set[str]:
    rows = (await session.execute(text("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'travel_city_quality_snapshot'
    """))).all()
    return {str(row.column_name) for row in rows}


def _empty_legacy_metrics() -> CityQualityMetrics:
    return CityQualityMetrics(
        valid_place_count=0,
        valid_evidence_count=0,
        covered_categories=(),
        successful_base_keywords=(),
        blocking_issues=(),
        gray_eligible=False,
        active_eligible=False,
        canonical_quality_pass=None,
        evidence_quality_pass=None,
    )


async def calculate_city_quality(
    session: AsyncSession,
    city: str,
) -> CityQualityMetrics:
    """Calculate canonical and evidence quality using fixed SQL rules."""
    if not await _has_city_foundation_schema(session):
        return _empty_legacy_metrics()

    metrics = (await session.execute(
        text(_QUALITY_METRICS_SQL),
        {"city": city, "food_place_types": list(_FOOD_PLACE_TYPES)},
    )).one()

    canonical_quality_pass = (
        int(metrics.route_eligible_activity_count) >= CANONICAL_MIN_ACTIVITY_COUNT
        and int(metrics.route_eligible_food_count) >= CANONICAL_MIN_FOOD_COUNT
        and int(metrics.route_eligible_type_coverage) >= CANONICAL_MIN_TYPE_COVERAGE
        and float(metrics.canonical_geo_resolved_ratio) >= CANONICAL_MIN_GEO_RATIO
    )
    evidence_quality_pass = (
        int(metrics.summary_effective_places) >= EVIDENCE_MIN_EFFECTIVE_PLACES
        and int(metrics.summary_effective_evidence) >= EVIDENCE_MIN_EFFECTIVE_EVIDENCE
        and int(metrics.summary_type_coverage) >= EVIDENCE_MIN_TYPE_COVERAGE
    )
    checks = (
        ("canonical_activity_count_insufficient", metrics.route_eligible_activity_count, CANONICAL_MIN_ACTIVITY_COUNT),
        ("canonical_food_count_insufficient", metrics.route_eligible_food_count, CANONICAL_MIN_FOOD_COUNT),
        ("canonical_type_coverage_insufficient", metrics.route_eligible_type_coverage, CANONICAL_MIN_TYPE_COVERAGE),
        ("canonical_geo_ratio_insufficient", metrics.canonical_geo_resolved_ratio, CANONICAL_MIN_GEO_RATIO),
        ("summary_effective_places_insufficient", metrics.summary_effective_places, EVIDENCE_MIN_EFFECTIVE_PLACES),
        ("summary_effective_evidence_insufficient", metrics.summary_effective_evidence, EVIDENCE_MIN_EFFECTIVE_EVIDENCE),
        ("summary_type_coverage_insufficient", metrics.summary_type_coverage, EVIDENCE_MIN_TYPE_COVERAGE),
    )
    covered_categories = tuple(
        f"type_coverage:{index + 1}"
        for index in range(int(metrics.summary_type_coverage))
    )
    return CityQualityMetrics(
        valid_place_count=(
            int(metrics.route_eligible_activity_count)
            + int(metrics.route_eligible_food_count)
        ),
        valid_evidence_count=int(metrics.summary_effective_evidence),
        covered_categories=covered_categories,
        successful_base_keywords=(),
        blocking_issues=tuple(code for code, actual, minimum in checks if actual < minimum),
        gray_eligible=canonical_quality_pass,
        active_eligible=canonical_quality_pass and evidence_quality_pass,
        route_eligible_activity_count=int(metrics.route_eligible_activity_count),
        route_eligible_food_count=int(metrics.route_eligible_food_count),
        route_eligible_type_coverage=int(metrics.route_eligible_type_coverage),
        canonical_geo_resolved_ratio=float(metrics.canonical_geo_resolved_ratio),
        canonical_quality_pass=canonical_quality_pass,
        summary_effective_places=int(metrics.summary_effective_places),
        summary_effective_evidence=int(metrics.summary_effective_evidence),
        summary_type_coverage=int(metrics.summary_type_coverage),
        evidence_quality_pass=evidence_quality_pass,
    )


async def inspect_city_quality(city_id: int) -> CityQualityMetrics:
    """Persist a quality snapshot and update city availability."""
    async with get_session_factory()() as session:
        city_row = (await session.execute(text("""
            SELECT canonical_name
            FROM travel_city
            WHERE id = :city_id
            FOR UPDATE
        """), {"city_id": city_id})).one()
        metrics = await calculate_city_quality(session, city_row.canonical_name)
        payload = {
            "city_id": city_id,
            "valid_place_count": metrics.valid_place_count,
            "valid_evidence_count": metrics.valid_evidence_count,
            "covered_categories": json.dumps(metrics.covered_categories, ensure_ascii=False),
            "successful_base_keywords": json.dumps(
                metrics.successful_base_keywords, ensure_ascii=False
            ),
            "blocking_issues": json.dumps(metrics.blocking_issues, ensure_ascii=False),
            "gray_eligible": metrics.gray_eligible,
            "active_eligible": metrics.active_eligible,
            "route_eligible_activity_count": metrics.route_eligible_activity_count,
            "route_eligible_food_count": metrics.route_eligible_food_count,
            "route_eligible_type_coverage": metrics.route_eligible_type_coverage,
            "canonical_geo_resolved_ratio": metrics.canonical_geo_resolved_ratio,
            "canonical_quality_pass": (
                metrics.canonical_quality_pass
                if metrics.canonical_quality_pass is not None
                else metrics.gray_eligible
            ),
            "summary_effective_places": metrics.summary_effective_places,
            "summary_effective_evidence": metrics.summary_effective_evidence,
            "summary_type_coverage": metrics.summary_type_coverage,
            "evidence_quality_pass": (
                metrics.evidence_quality_pass
                if metrics.evidence_quality_pass is not None
                else metrics.active_eligible
            ),
        }
        existing_columns = await _snapshot_columns(session)
        column_specs = [
            item
            for item in [*_BASE_SNAPSHOT_COLUMNS, *_V0615_SNAPSHOT_COLUMNS]
            if item[0] in existing_columns
        ]
        column_sql = ", ".join(column for column, _ in column_specs)
        value_sql = ", ".join(value for _, value in column_specs)
        await session.execute(text("""
            INSERT INTO travel_city_quality_snapshot ({column_sql})
            VALUES ({value_sql})
        """.format(column_sql=column_sql, value_sql=value_sql)), payload)
        await session.execute(text("""
            UPDATE travel_city
            SET status = CASE
                    WHEN status = 'DISABLED' THEN 'DISABLED'
                    WHEN :active_eligible AND active_confirmed_time IS NOT NULL
                        THEN 'ACTIVE'
                    WHEN :gray_eligible THEN 'GRAY'
                    ELSE 'DISCOVERED'
                END,
                last_quality_check_time = NOW()
            WHERE id = :city_id
        """), payload)
        await session.commit()
    return metrics
