"""Human review and publication operations for canonical place facts."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Literal, Mapping
from urllib.parse import urlparse

from sqlalchemy import text

from src.agents.evidence_strength import _classify_signal
from src.pipeline.db import get_session_factory


DraftStatus = Literal["draft", "approved", "rejected", "published"]

DRAFT_STATUSES: tuple[DraftStatus, ...] = (
    "draft",
    "approved",
    "rejected",
    "published",
)

FACT_INSERT_SQL = """
    INSERT INTO travel_place_fact
        (place_id, source_platform, source_id, source_url,
         fact_type, fact_value, confidence)
    VALUES
        (:pid, 'manual', :source_id, :source_url,
         'recommendation', CAST(:fact_value AS jsonb), :confidence)
    RETURNING id
"""

_ALLOWED_TRANSITIONS: dict[DraftStatus, frozenset[DraftStatus]] = {
    "draft": frozenset({"approved", "rejected"}),
    "approved": frozenset({"published"}),
    "rejected": frozenset(),
    "published": frozenset(),
}


@dataclass(frozen=True)
class ClassificationResult:
    strength: str
    rule_id: str
    rule_layer: str
    reason: str
    marker: str
    direct_fact: bool
    warning: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _required_text(name: str, value: Any) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise ValueError(f"{name} is required")
    return cleaned


def validate_draft_fields(
    *,
    place_id: int,
    fact_text: str,
    source_url: str,
    source_quote: str,
) -> dict[str, Any]:
    if int(place_id) <= 0:
        raise ValueError("place_id must be a positive canonical place id")
    cleaned_url = _required_text("source_url", source_url)
    parsed_url = urlparse(cleaned_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise ValueError("source_url must be an absolute http(s) URL")
    return {
        "place_id": int(place_id),
        "fact_text": _required_text("fact_text", fact_text),
        "source_url": cleaned_url,
        "source_quote": _required_text("source_quote", source_quote),
    }


def validate_transition(current: str, target: str) -> None:
    if current not in DRAFT_STATUSES:
        raise ValueError(f"unknown draft status: {current}")
    if target not in DRAFT_STATUSES:
        raise ValueError(f"unknown target status: {target}")
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise ValueError(f"invalid fact draft transition: {current} -> {target}")


def publish_decision(status: str, published_fact_id: int | None) -> str:
    """Return insert/skip or reject an illegal publication attempt."""
    if status == "published":
        if published_fact_id is None:
            raise ValueError("published draft is missing published_fact_id")
        return "skip"
    validate_transition(status, "published")
    if published_fact_id is not None:
        raise ValueError("unpublished draft already has published_fact_id")
    return "insert"


def classify_fact_text(fact_text: str) -> ClassificationResult:
    signal = _classify_signal(_required_text("fact_text", fact_text), "top_reason")
    warning: str | None = None
    if signal.strength != "direct_fact":
        if signal.rule_id == "l4_unknown_signal":
            warning = (
                "Not Writer-authorized: the text has no L2 direct-fact marker. "
                "Do not invent a marker; rewrite only with source-supported objective "
                "properties such as free admission, walking distance, steps/slope/elevator, "
                "or food/rest facilities, or review the classifier contract separately."
            )
        elif signal.strength == "not_authorized":
            warning = (
                "Not Writer-authorized: remove marketing, recommendation, photo, or "
                "subjective evaluation language before approval."
            )
        elif signal.strength == "risk_only_warning":
            warning = (
                "Not a direct fact: the classifier treats this as warning-only evidence."
            )
        elif signal.strength == "weak_experience":
            warning = (
                "Not a direct fact: the classifier treats this as weak experience evidence."
            )
        else:
            warning = "Not Writer-authorized by the current evidence classifier."
    return ClassificationResult(
        strength=signal.strength,
        rule_id=signal.rule_id,
        rule_layer=signal.rule_layer,
        reason=signal.reason,
        marker=signal.marker,
        direct_fact=signal.strength == "direct_fact",
        warning=warning,
    )


def build_fact_insert_params(
    draft: Mapping[str, Any],
    *,
    fact_place_id: int,
) -> dict[str, Any]:
    draft_id = int(draft["id"])
    return {
        "pid": int(fact_place_id),
        "source_id": f"place_fact_draft:{draft_id}",
        "source_url": _required_text("source_url", draft["source_url"]),
        "fact_value": json.dumps(
            {
                "reason": _required_text("fact_text", draft["fact_text"]),
                "evidence": _required_text(
                    "source_quote", draft["source_quote"]
                ),
            },
            ensure_ascii=False,
        ),
        "confidence": 1.0,
    }


async def add_draft(
    *,
    place_id: int,
    fact_text: str,
    source_url: str,
    source_quote: str,
) -> dict[str, Any]:
    params = validate_draft_fields(
        place_id=place_id,
        fact_text=fact_text,
        source_url=source_url,
        source_quote=source_quote,
    )
    async with get_session_factory()() as session:
        place = (await session.execute(text("""
            SELECT place_id, canonical_name, city
            FROM travel_canonical_place
            WHERE place_id = :place_id
        """), {"place_id": params["place_id"]})).mappings().one_or_none()
        if place is None:
            raise ValueError(f"canonical place not found: {params['place_id']}")
        row = (await session.execute(text("""
            INSERT INTO travel_place_fact_draft (
                place_id, fact_text, source_url, source_quote
            ) VALUES (
                :place_id, :fact_text, :source_url, :source_quote
            )
            RETURNING id, place_id, fact_text, source_url, source_quote,
                      status, review_note, created_at, reviewed_at,
                      published_fact_id
        """), params)).mappings().one()
        await session.commit()
    result = dict(row)
    result["canonical_name"] = place["canonical_name"]
    result["city"] = place["city"]
    return result


async def list_drafts(
    *,
    status: str | None = None,
    city: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    if status is not None and status not in DRAFT_STATUSES:
        raise ValueError(f"unknown draft status: {status}")
    if limit <= 0:
        raise ValueError("limit must be positive")
    clauses: list[str] = []
    params: dict[str, Any] = {"limit": limit}
    if status:
        clauses.append("d.status = :status")
        params["status"] = status
    if city:
        clauses.append("c.city = :city")
        params["city"] = city.strip()
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    async with get_session_factory()() as session:
        rows = (await session.execute(text(f"""
            SELECT d.id, d.place_id, c.canonical_name, c.city,
                   d.fact_text, d.source_url, d.source_quote, d.status,
                   d.review_note, d.created_at, d.reviewed_at,
                   d.published_fact_id
            FROM travel_place_fact_draft AS d
            JOIN travel_canonical_place AS c ON c.place_id = d.place_id
            {where}
            ORDER BY d.created_at, d.id
            LIMIT :limit
        """), params)).mappings().all()
    return [dict(row) for row in rows]


async def review_draft(
    draft_id: int,
    *,
    action: Literal["approve", "reject"],
    note: str | None = None,
) -> dict[str, Any]:
    if action not in {"approve", "reject"}:
        raise ValueError(f"unsupported review action: {action}")
    target: DraftStatus = "approved" if action == "approve" else "rejected"
    cleaned_note = str(note or "").strip() or None
    if target == "rejected" and cleaned_note is None:
        raise ValueError("review note is required when rejecting a fact draft")
    async with get_session_factory()() as session:
        current = (await session.execute(text("""
            SELECT id, status
            FROM travel_place_fact_draft
            WHERE id = :draft_id
            FOR UPDATE
        """), {"draft_id": draft_id})).one_or_none()
        if current is None:
            raise ValueError(f"fact draft not found: {draft_id}")
        validate_transition(str(current.status), target)
        row = (await session.execute(text("""
            UPDATE travel_place_fact_draft
            SET status = :status,
                review_note = :review_note,
                reviewed_at = NOW()
            WHERE id = :draft_id
            RETURNING id, place_id, fact_text, source_url, source_quote,
                      status, review_note, created_at, reviewed_at,
                      published_fact_id
        """), {
            "draft_id": draft_id,
            "status": target,
            "review_note": cleaned_note,
        })).mappings().one()
        await session.commit()
    return dict(row)


def _publish_select_sql(*, single: bool, lock: bool) -> str:
    condition = "d.id = :draft_id" if single else "d.status = 'approved'"
    limit = "" if single else "LIMIT :limit"
    lock_clause = "FOR UPDATE OF d" if lock else ""
    return f"""
        SELECT d.id, d.place_id, d.fact_text, d.source_url, d.source_quote,
               d.status, d.review_note, d.created_at, d.reviewed_at,
               d.published_fact_id, c.canonical_name, c.city,
               s.place_id AS fact_place_id
        FROM travel_place_fact_draft AS d
        JOIN travel_canonical_place AS c ON c.place_id = d.place_id
        LEFT JOIN travel_place_summary AS s
          ON s.canonical_place_id = d.place_id
        WHERE {condition}
        ORDER BY d.id
        {limit}
        {lock_clause}
    """


async def publish_approved(
    *,
    draft_id: int | None = None,
    limit: int = 100,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    if limit <= 0:
        raise ValueError("limit must be positive")
    params: dict[str, Any] = (
        {"draft_id": draft_id} if draft_id is not None else {"limit": limit}
    )
    async with get_session_factory()() as session:
        rows = (await session.execute(
            text(_publish_select_sql(single=draft_id is not None, lock=not dry_run)),
            params,
        )).mappings().all()
        if draft_id is not None and not rows:
            raise ValueError(f"fact draft not found: {draft_id}")

        results: list[dict[str, Any]] = []
        for raw_row in rows:
            row = dict(raw_row)
            decision = publish_decision(
                str(row["status"]), row.get("published_fact_id")
            )
            classification = classify_fact_text(str(row["fact_text"])).to_dict()
            base_result = {
                "draft_id": int(row["id"]),
                "canonical_place_id": int(row["place_id"]),
                "canonical_name": row["canonical_name"],
                "city": row["city"],
                "classification": classification,
                "writer_authorized": classification["direct_fact"],
                "summary_refresh_required": True,
            }
            if decision == "skip":
                results.append({
                    **base_result,
                    "action": "skipped",
                    "reason": "already_published",
                    "published_fact_id": int(row["published_fact_id"]),
                })
                continue
            if row["fact_place_id"] is None:
                results.append({
                    **base_result,
                    "action": "blocked",
                    "reason": "canonical_place_has_no_summary_attachment",
                })
                continue

            insert_params = build_fact_insert_params(
                row, fact_place_id=int(row["fact_place_id"])
            )
            if dry_run:
                results.append({
                    **base_result,
                    "action": "would_publish",
                    "sql": " ".join(FACT_INSERT_SQL.split()),
                    "params": insert_params,
                })
                continue

            fact_id = int((await session.execute(
                text(FACT_INSERT_SQL), insert_params
            )).scalar_one())
            updated_fact_id = (await session.execute(text("""
                UPDATE travel_place_fact_draft
                SET status = 'published', published_fact_id = :fact_id
                WHERE id = :draft_id AND status = 'approved'
                RETURNING published_fact_id
            """), {
                "draft_id": row["id"],
                "fact_id": fact_id,
            })).scalar_one_or_none()
            if updated_fact_id is None:
                raise ValueError(
                    f"fact draft is no longer approved: {row['id']}"
                )
            results.append({
                **base_result,
                "action": "published",
                "published_fact_id": fact_id,
            })

        if dry_run:
            await session.rollback()
        else:
            await session.commit()
    return results


async def verify_draft(draft_id: int) -> dict[str, Any]:
    async with get_session_factory()() as session:
        row = (await session.execute(text("""
            SELECT d.id, d.place_id, c.canonical_name, c.city, d.fact_text,
                   d.status, d.published_fact_id,
                   (f.id IS NOT NULL) AS published_fact_exists
            FROM travel_place_fact_draft AS d
            JOIN travel_canonical_place AS c ON c.place_id = d.place_id
            LEFT JOIN travel_place_fact AS f ON f.id = d.published_fact_id
            WHERE d.id = :draft_id
        """), {"draft_id": draft_id})).mappings().one_or_none()
    if row is None:
        raise ValueError(f"fact draft not found: {draft_id}")
    result = dict(row)
    result["classification"] = classify_fact_text(
        str(result["fact_text"])
    ).to_dict()
    result["writer_authorized"] = result["classification"]["direct_fact"]
    result["summary_refresh_required"] = True
    return result
