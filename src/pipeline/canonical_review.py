"""Manual review operations for canonical POI candidates."""

from __future__ import annotations

from sqlalchemy import text

from src.pipeline.canonical_onboarding import _write_event
from src.pipeline.db import get_session_factory


async def list_pending(city: str | None = None, limit: int = 100) -> list[dict]:
    where = "WHERE review_status = 'pending_review'"
    params: dict[str, object] = {"limit": limit}
    if city:
        where += " AND city = :city"
        params["city"] = city
    async with get_session_factory()() as session:
        rows = (await session.execute(text(f"""
            SELECT place_id, canonical_name, city, place_type, address,
                   amap_poi_id, trust_level, review_status, geo_status
            FROM travel_canonical_place
            {where}
            ORDER BY city, canonical_name
            LIMIT :limit
        """), params)).mappings().all()
    return [dict(row) for row in rows]


async def transition(
    place_id: int,
    *,
    action: str,
    operator_id: str,
    reason: str,
) -> None:
    targets = {
        "approve": ("trusted", "reviewed", True),
        "reject": ("rejected", "rejected", False),
        "reopen": ("candidate", "pending_review", True),
    }
    if action not in targets:
        raise ValueError(f"unsupported review action: {action}")
    trust, review, active = targets[action]
    async with get_session_factory()() as session:
        row = (await session.execute(text("""
            SELECT place_id, trust_level, review_status
            FROM travel_canonical_place
            WHERE place_id = :place_id
            FOR UPDATE
        """), {"place_id": place_id})).one_or_none()
        if row is None:
            raise ValueError(f"canonical place not found: {place_id}")
        await session.execute(text("""
            UPDATE travel_canonical_place
            SET trust_level = :trust,
                review_status = :review,
                is_active = :active
            WHERE place_id = :place_id
        """), {
            "place_id": place_id,
            "trust": trust,
            "review": review,
            "active": active,
        })
        await _write_event(
            session,
            place_id=place_id,
            action=action,
            from_trust=row.trust_level,
            from_review=row.review_status,
            to_trust=trust,
            to_review=review,
            reason_code="manual_review",
            operator_id=operator_id,
            metadata={"reason": reason},
        )
        await session.commit()


async def merge(
    source_place_id: int,
    target_place_id: int,
    *,
    operator_id: str,
    reason: str,
) -> None:
    if source_place_id == target_place_id:
        raise ValueError("source and target must be different")
    async with get_session_factory()() as session:
        rows = (await session.execute(text("""
            SELECT place_id, canonical_name, trust_level, review_status
            FROM travel_canonical_place
            WHERE place_id IN (:source_id, :target_id)
            ORDER BY place_id
            FOR UPDATE
        """), {
            "source_id": source_place_id,
            "target_id": target_place_id,
        })).all()
        by_id = {int(row.place_id): row for row in rows}
        if source_place_id not in by_id or target_place_id not in by_id:
            raise ValueError("source or target canonical place not found")
        source = by_id[source_place_id]
        target = by_id[target_place_id]
        await session.execute(text("""
            UPDATE travel_place_summary
            SET canonical_place_id = :target_id
            WHERE canonical_place_id = :source_id
        """), {"source_id": source_place_id, "target_id": target_place_id})
        await session.execute(text("""
            INSERT INTO travel_canonical_place_source (
                canonical_place_id, source_type, source_name, source_url,
                source_rank, source_place_name, evidence_summary, collected_at
            )
            SELECT
                :target_id, source_type, source_name, source_url,
                source_rank, source_place_name, evidence_summary, collected_at
            FROM travel_canonical_place_source
            WHERE canonical_place_id = :source_id
            ON CONFLICT DO NOTHING
        """), {"source_id": source_place_id, "target_id": target_place_id})
        await session.execute(text("""
            DELETE FROM travel_canonical_place_source
            WHERE canonical_place_id = :source_id
        """), {"source_id": source_place_id})
        await session.execute(text("""
            INSERT INTO travel_place_alias (
                canonical_place_id, alias_name, normalized_alias,
                relation_type, status, source, confidence, note
            ) VALUES (
                :target_id, :alias, :alias,
                'alias_same', 'confirmed', 'manual', 1.0, :note
            )
            ON CONFLICT (canonical_place_id, normalized_alias) DO UPDATE
            SET status = 'confirmed', source = 'manual', confidence = 1.0, note = :note
        """), {
            "target_id": target_place_id,
            "alias": source.canonical_name,
            "note": f"Merged from canonical place {source_place_id}",
        })
        await session.execute(text("""
            UPDATE travel_canonical_place
            SET trust_level = 'rejected',
                review_status = 'rejected',
                is_active = FALSE
            WHERE place_id = :source_id
        """), {"source_id": source_place_id})
        await _write_event(
            session,
            place_id=source_place_id,
            action="merge",
            from_trust=source.trust_level,
            from_review=source.review_status,
            to_trust="rejected",
            to_review="rejected",
            reason_code="manual_merge",
            operator_id=operator_id,
            merge_target_place_id=target_place_id,
            metadata={"reason": reason, "target_name": target.canonical_name},
        )
        await session.commit()
