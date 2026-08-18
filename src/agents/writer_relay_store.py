"""PostgreSQL authority for v0.9.4.2+ Writer relay admission.

The ledger stores endpoint names and safe classifications only. Prompts,
consumer input, relay URLs, credentials and raw relay responses never enter it.

An ``OUTCOME_UNKNOWN`` dispatch has two distinguishable causes. The original
v0.9.4.2 form has ``safe_failure_class=PROCESS_LOSS`` because the process lost
the upstream outcome. A v0.9.6 probe-killed dispatch whose connection could not
be confirmed closed keeps ``safe_failure_class=TIMEOUT`` while its
``DISPATCHED`` lease is held pessimistically to expiry, then becomes
``OUTCOME_UNKNOWN``. Neither form is ever resent automatically.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from sqlalchemy import text

from src.pipeline.db import get_session_factory

logger = logging.getLogger(__name__)

PARTICIPATING_ENDPOINTS = (
    "centos",
    "shuai",
    "gateai",
)
ACTIVE_ENDPOINTS = frozenset({"centos", "shuai"})
CANARY_ENDPOINTS = frozenset({"gateai"})
RETIRED_ENDPOINTS = frozenset({"venlacy", "aixoras"})
OWNER_OVERRIDE_PROMOTION_ENDPOINTS = frozenset({"shuai"})
FROZEN_ENDPOINT_POLICY: dict[str, tuple[str, int, int]] = {
    "aixoras": ("CANARY", 2, 2),
    "centos": ("ACTIVE", 3, 3),
    "shuai": ("ACTIVE", 3, 3),
    "kuaipao": ("DISABLED", 0, 0),
    "gateai": ("CANARY", 2, 2),
    "venlacy": ("DISABLED", 0, 0),
    "keungliang": ("DISABLED", 0, 0),
    "4router": ("DISABLED", 0, 0),
}
TERMINAL_DISPATCH_STATES = frozenset({"SUCCEEDED", "FAILED", "OUTCOME_UNKNOWN"})
COOLDOWN_SECONDS = (60, 120, 300)
PENDING_POLICY_COMPENSATION_SECONDS = 180


@dataclass(frozen=True)
class EndpointCapacity:
    name: str
    participation: str
    circuit_state: str
    inflight: int
    cap: int
    pending_policy_count: int = 0


@dataclass(frozen=True)
class DispatchClaim:
    status: Literal["CLAIMED", "BUSY", "UNAVAILABLE", "DUPLICATE"]
    endpoint_name: str | None = None
    dispatch_id: uuid.UUID | None = None
    snapshot: tuple[EndpointCapacity, ...] = ()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _validate_promotion(
    name: str,
    row: Any,
    *,
    active_rates: list[float],
    owner_override: bool,
) -> None:
    if str(row["participation"]) != "CANARY":
        raise ValueError("only CANARY endpoints may be promoted")
    if owner_override:
        if name not in OWNER_OVERRIDE_PROMOTION_ENDPOINTS:
            raise ValueError("owner override is authorized only for shuai")
        if str(row["qualification_state"]) != "QUALIFIED":
            raise ValueError("owner override requires a QUALIFIED endpoint")
        if str(row["circuit_state"]) != "CLOSED":
            raise ValueError("owner override requires a CLOSED circuit")
        if int(row["pending_policy_count"]):
            raise ValueError("owner override blocked by pending policy action")
        return

    observations = int(row["observation_count"])
    successes = int(row["transport_success_count"])
    timeouts = int(row["timeout_count"])
    rejected = int(row["auth_policy_rejection_count"])
    valid = int(row["contract_valid_count"])
    if observations < 20:
        raise ValueError("promotion requires at least 20 observations")
    if successes / observations < 0.95 or timeouts / observations > 0.05:
        raise ValueError("promotion transport/timeout threshold not met")
    if rejected:
        raise ValueError("promotion blocked by auth/policy rejection")
    active_rate = sum(active_rates) / len(active_rates) if active_rates else 1.0
    if valid / observations < active_rate - 0.05:
        raise ValueError("promotion contract-valid threshold not met")


class PostgresWriterRelayStore:
    """Cross-process single-winner admission backed by PostgreSQL."""

    def __init__(self, session_factory=None) -> None:
        self._session_factory = session_factory or get_session_factory()

    async def synchronize_endpoints(self, fingerprints: dict[str, str]) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": "writer-relay-config-v0942"},
            )
            for name, (participation, cap, weight) in FROZEN_ENDPOINT_POLICY.items():
                await session.execute(
                    text(
                        """
                        INSERT INTO travel_relay_endpoint_state (
                            endpoint_name, participation, previous_participation,
                            max_inflight, routing_weight, qualification_state
                        ) VALUES (
                            :name, :participation, :participation,
                            :cap, :weight, :qualification
                        )
                        ON CONFLICT (endpoint_name) DO NOTHING
                        """
                    ),
                    {
                        "name": name,
                        "participation": participation,
                        "cap": cap,
                        "weight": weight,
                        "qualification": (
                            "QUALIFIED"
                            if name in PARTICIPATING_ENDPOINTS
                            else "UNQUALIFIED"
                        ),
                    },
                )
            for name in RETIRED_ENDPOINTS:
                await session.execute(
                    text(
                        """
                        UPDATE travel_relay_endpoint_state
                        SET participation = 'DISABLED',
                            previous_participation = 'DISABLED',
                            max_inflight = 0,
                            routing_weight = 0,
                            qualification_state = 'UNQUALIFIED',
                            circuit_state = 'CLOSED',
                            cooldown_until = NULL,
                            probe_owner = NULL,
                            probe_lease_expires_at = NULL,
                            updated_at = NOW()
                        WHERE endpoint_name = :name
                        """
                    ),
                    {"name": name},
                )
            for name, fingerprint in fingerprints.items():
                await session.execute(
                    text(
                        """
                        UPDATE travel_relay_endpoint_state
                        SET configuration_fingerprint = :fingerprint,
                            qualification_state = CASE
                                WHEN configuration_fingerprint IN ('', :fingerprint)
                                    THEN qualification_state
                                ELSE 'UNQUALIFIED'
                            END,
                            circuit_state = CASE
                                WHEN configuration_fingerprint NOT IN ('', :fingerprint)
                                    THEN 'QUARANTINED'
                                ELSE circuit_state
                            END,
                            updated_at = NOW()
                        WHERE endpoint_name = :name
                        """
                    ),
                    {"name": name, "fingerprint": fingerprint},
                )
            await self._compensate_stale_policy_rejections(session)

    async def _compensate_stale_policy_rejections(self, session) -> None:
        rows = (
            (
                await session.execute(
                    text(
                        """
                        WITH finalized AS (
                            UPDATE travel_writer_dispatch
                            SET safe_failure_class = 'POLICY_REJECTION_APPLIED',
                                updated_at = NOW()
                            WHERE dispatch_id IN (
                                SELECT dispatch_id
                                FROM travel_writer_dispatch
                                WHERE safe_failure_class = 'POLICY_REJECTION'
                                  AND updated_at <= NOW() - make_interval(secs => :stale_seconds)
                                FOR UPDATE SKIP LOCKED
                            )
                            RETURNING endpoint_name
                        ), counts AS (
                            SELECT endpoint_name, COUNT(*)::INT AS failure_count
                            FROM finalized
                            GROUP BY endpoint_name
                        )
                        UPDATE travel_relay_endpoint_state AS endpoint
                        SET pending_policy_count = GREATEST(
                                0, endpoint.pending_policy_count - counts.failure_count
                            ),
                            observation_count = endpoint.observation_count + counts.failure_count,
                            auth_policy_rejection_count =
                                endpoint.auth_policy_rejection_count + counts.failure_count,
                            circuit_state = 'QUARANTINED',
                            qualification_state = 'UNQUALIFIED',
                            updated_at = NOW()
                        FROM counts
                        WHERE endpoint.endpoint_name = counts.endpoint_name
                        RETURNING endpoint.endpoint_name, counts.failure_count
                        """
                    ),
                    {"stale_seconds": PENDING_POLICY_COMPENSATION_SECONDS},
                )
            )
            .mappings()
            .all()
        )
        for row in rows:
            logger.warning(
                "writer_relay_pending_policy_compensated endpoint=%s count=%s",
                row["endpoint_name"],
                row["failure_count"],
            )

    async def _reap_expired(self, session) -> None:
        await session.execute(
            text(
                """
                UPDATE travel_writer_dispatch
                SET state = CASE
                        WHEN state = 'DISPATCHED' THEN 'OUTCOME_UNKNOWN'
                        ELSE 'FAILED'
                    END,
                    safe_failure_class = CASE
                        WHEN state = 'DISPATCHED' THEN COALESCE(
                            safe_failure_class, 'PROCESS_LOSS'
                        )
                        ELSE 'CLAIM_EXPIRED'
                    END,
                    finished_at = NOW(), updated_at = NOW()
                WHERE state IN ('CLAIMED', 'DISPATCHED')
                  AND lease_expires_at <= NOW()
                """
            )
        )

    async def claim(
        self,
        *,
        logical_call_id: uuid.UUID,
        ordinal: int,
        job_id: str | None,
        call_reason: str,
        model: str,
        release_identity: str,
        fingerprints: dict[str, str],
        initial: bool,
        exclude_endpoints: frozenset[str],
        lease_seconds: float,
        now: datetime | None = None,
    ) -> DispatchClaim:
        del now
        async with self._session_factory() as session, session.begin():
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": "writer-relay-admission-v0942"},
            )
            await self._reap_expired(session)
            await self._compensate_stale_policy_rejections(session)
            existing = await session.execute(
                text(
                    """
                    SELECT dispatch_id, endpoint_name
                    FROM travel_writer_dispatch
                    WHERE logical_call_id = :logical_call_id AND ordinal = :ordinal
                    """
                ),
                {"logical_call_id": logical_call_id, "ordinal": ordinal},
            )
            duplicate = existing.mappings().first()
            if duplicate is not None:
                return DispatchClaim(
                    "DUPLICATE",
                    endpoint_name=str(duplicate["endpoint_name"]),
                    dispatch_id=duplicate["dispatch_id"],
                )
            rows = list(
                (
                    await session.execute(
                        text(
                            """
                            SELECT endpoint_name, participation, circuit_state,
                                   qualification_state, max_inflight,
                                   routing_weight, configuration_fingerprint,
                                   selection_current, pending_policy_count
                            FROM travel_relay_endpoint_state
                            WHERE endpoint_name = ANY(:names)
                            FOR UPDATE
                            """
                        ),
                        {"names": list(fingerprints)},
                    )
                ).mappings()
            )
            inflight_rows = list(
                (
                    await session.execute(
                        text(
                            """
                            SELECT endpoint_name, COUNT(*) AS inflight
                            FROM travel_writer_dispatch
                            WHERE state IN ('CLAIMED', 'DISPATCHED')
                              AND lease_expires_at > NOW()
                            GROUP BY endpoint_name
                            """
                        )
                    )
                ).mappings()
            )
            inflight = {
                str(row["endpoint_name"]): int(row["inflight"]) for row in inflight_rows
            }
            snapshot = tuple(
                EndpointCapacity(
                    name=str(row["endpoint_name"]),
                    participation=str(row["participation"]),
                    circuit_state=str(row["circuit_state"]),
                    inflight=inflight.get(str(row["endpoint_name"]), 0),
                    cap=int(row["max_inflight"]),
                    pending_policy_count=int(row["pending_policy_count"]),
                )
                for row in rows
            )
            for item in snapshot:
                if item.inflight > item.cap:
                    logger.critical(
                        "writer_relay_cap_breach endpoint=%s inflight=%s cap=%s",
                        item.name,
                        item.inflight,
                        item.cap,
                    )
            eligible = []
            for row in rows:
                name = str(row["endpoint_name"])
                participation = str(row["participation"])
                if name in exclude_endpoints:
                    continue
                if participation not in (
                    {"ACTIVE", "CANARY"} if initial else {"ACTIVE"}
                ):
                    continue
                if str(row["qualification_state"]) != "QUALIFIED":
                    continue
                if str(row["circuit_state"]) != "CLOSED":
                    continue
                if int(row["pending_policy_count"]) > 0:
                    continue
                if str(row["configuration_fingerprint"]) != fingerprints.get(name):
                    continue
                eligible.append(row)
            if not eligible:
                return DispatchClaim("UNAVAILABLE", snapshot=snapshot)
            free = [
                row
                for row in eligible
                if inflight.get(str(row["endpoint_name"]), 0) < int(row["max_inflight"])
            ]
            if not free:
                return DispatchClaim("BUSY", snapshot=snapshot)

            total_weight = sum(int(row["routing_weight"]) for row in free)
            scored = [
                (
                    int(row["selection_current"]) + int(row["routing_weight"]),
                    str(row["endpoint_name"]),
                    row,
                )
                for row in free
            ]
            _score, selected_name, _selected = max(
                scored, key=lambda item: (item[0], item[1])
            )
            for score, name, _row in scored:
                await session.execute(
                    text(
                        """
                        UPDATE travel_relay_endpoint_state
                        SET selection_current = :score,
                            selection_count = selection_count + :selected,
                            peak_inflight = GREATEST(peak_inflight, :peak_inflight),
                            updated_at = NOW()
                        WHERE endpoint_name = :name
                        """
                    ),
                    {
                        "name": name,
                        "score": score - total_weight
                        if name == selected_name
                        else score,
                        "selected": 1 if name == selected_name else 0,
                        "peak_inflight": (
                            inflight.get(name, 0) + 1
                            if name == selected_name
                            else inflight.get(name, 0)
                        ),
                    },
                )
            dispatch_id = uuid.uuid4()
            await session.execute(
                text(
                    """
                    INSERT INTO travel_writer_dispatch (
                        dispatch_id, job_id, logical_call_id, ordinal,
                        call_reason, endpoint_name, model, release_identity,
                        state, lease_expires_at
                    ) VALUES (
                        :dispatch_id, :job_id, :logical_call_id, :ordinal,
                        :call_reason, :endpoint_name, :model, :release_identity,
                        'CLAIMED', NOW() + make_interval(secs => :lease_seconds)
                    )
                    """
                ),
                {
                    "dispatch_id": dispatch_id,
                    "job_id": job_id,
                    "logical_call_id": logical_call_id,
                    "ordinal": ordinal,
                    "call_reason": call_reason[:128],
                    "endpoint_name": selected_name,
                    "model": model,
                    "release_identity": release_identity,
                    "lease_seconds": float(lease_seconds),
                },
            )
            if job_id:
                dispatch_count = await session.scalar(
                    text(
                        "SELECT COUNT(*) FROM travel_writer_dispatch WHERE job_id = :job_id"
                    ),
                    {"job_id": job_id},
                )
                if int(dispatch_count or 0) > 4:
                    logger.warning(
                        "writer_relay_dispatch_count_alert job_id=%s count=%s release=%s",
                        job_id,
                        dispatch_count,
                        release_identity,
                    )
            return DispatchClaim(
                "CLAIMED",
                endpoint_name=selected_name,
                dispatch_id=dispatch_id,
                snapshot=snapshot,
            )

    async def mark_dispatched(self, dispatch_id: uuid.UUID) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(
                text(
                    """
                    UPDATE travel_writer_dispatch
                    SET state = 'DISPATCHED', dispatched_at = NOW(), updated_at = NOW()
                    WHERE dispatch_id = :dispatch_id AND state = 'CLAIMED'
                    """
                ),
                {"dispatch_id": dispatch_id},
            )

    async def complete_success(
        self, dispatch_id: uuid.UUID, *, latency_ms: int
    ) -> None:
        async with self._session_factory() as session, session.begin():
            row = (
                (
                    await session.execute(
                        text(
                            """
                        UPDATE travel_writer_dispatch
                        SET state = 'SUCCEEDED', finished_at = NOW(),
                            latency_ms = :latency_ms, updated_at = NOW()
                        WHERE dispatch_id = :dispatch_id AND state = 'DISPATCHED'
                        RETURNING endpoint_name
                        """
                        ),
                        {"dispatch_id": dispatch_id, "latency_ms": max(0, latency_ms)},
                    )
                )
                .mappings()
                .first()
            )
            if row is not None:
                await session.execute(
                    text(
                        """
                        UPDATE travel_relay_endpoint_state
                        SET observation_count = observation_count + 1,
                            transport_success_count = transport_success_count + 1,
                            contract_valid_count = contract_valid_count + 1,
                            consecutive_invalid_output = 0,
                            updated_at = NOW()
                        WHERE endpoint_name = :name
                        """
                    ),
                    {"name": row["endpoint_name"]},
                )

    async def complete_failure(
        self,
        dispatch_id: uuid.UUID,
        *,
        latency_ms: int,
        failure_class: str,
        http_status_class: str | None = None,
        failure_signature: str | None = None,
        retry_after_seconds: float | None = None,
        transport_succeeded: bool = False,
        release_capacity: bool = True,
    ) -> bool:
        """Record failure and detect a same-call shared request defect.

        ``release_capacity=False`` is reserved for a v0.9.6 probe timeout whose
        transport close could not be confirmed. It records TIMEOUT and applies
        endpoint health attribution immediately, but deliberately leaves the
        dispatch in ``DISPATCHED`` until lease expiry. The reaper then produces
        ``OUTCOME_UNKNOWN + TIMEOUT`` rather than the native process-loss form.
        """
        if not release_capacity and failure_class != "TIMEOUT":
            raise ValueError(
                "release_capacity=False is reserved for probe TIMEOUT"
            )
        async with self._session_factory() as session, session.begin():
            row = (
                (
                    await session.execute(
                        text(
                            """
                        UPDATE travel_writer_dispatch
                        SET state = CASE
                                WHEN :release_capacity THEN 'FAILED'
                                ELSE state
                            END,
                            finished_at = CASE
                                WHEN :release_capacity THEN NOW()
                                ELSE finished_at
                            END,
                            latency_ms = :latency_ms,
                            safe_failure_class = :failure_class,
                            http_status_class = :http_status_class,
                            failure_signature = :failure_signature,
                            updated_at = NOW()
                        WHERE dispatch_id = :dispatch_id
                          AND state IN ('CLAIMED', 'DISPATCHED')
                          AND (
                              :release_capacity
                              OR (
                                  state = 'DISPATCHED'
                                  AND safe_failure_class IS NULL
                              )
                          )
                        RETURNING endpoint_name, logical_call_id
                        """
                        ),
                        {
                            "dispatch_id": dispatch_id,
                            "latency_ms": max(0, latency_ms),
                            "failure_class": failure_class[:64],
                            "http_status_class": http_status_class,
                            "failure_signature": failure_signature,
                            "release_capacity": release_capacity,
                        },
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                return False
            name = str(row["endpoint_name"])
            if failure_class == "POLICY_REJECTION" and failure_signature:
                await session.execute(
                    text(
                        """
                        UPDATE travel_relay_endpoint_state
                        SET pending_policy_count = pending_policy_count + 1,
                            updated_at = NOW()
                        WHERE endpoint_name = :name
                        """
                    ),
                    {"name": name},
                )
                shared_endpoints = list(
                    (
                        await session.scalars(
                            text(
                                """
                                SELECT DISTINCT endpoint_name
                                FROM travel_writer_dispatch
                                WHERE logical_call_id = :logical_call_id
                                  AND failure_signature = :signature
                                  AND safe_failure_class = 'POLICY_REJECTION'
                                """
                            ),
                            {
                                "logical_call_id": row["logical_call_id"],
                                "signature": failure_signature,
                            },
                        )
                    ).all()
                )
                if len(shared_endpoints) < 2:
                    return False
                await session.execute(
                    text(
                        """
                        UPDATE travel_writer_dispatch
                        SET safe_failure_class = 'SHARED_REQUEST_CONTRACT',
                            updated_at = NOW()
                        WHERE logical_call_id = :logical_call_id
                          AND failure_signature = :signature
                          AND safe_failure_class = 'POLICY_REJECTION'
                        """
                    ),
                    {
                        "logical_call_id": row["logical_call_id"],
                        "signature": failure_signature,
                    },
                )
                await session.execute(
                    text(
                        """
                        UPDATE travel_relay_endpoint_state
                        SET pending_policy_count = GREATEST(
                                0, pending_policy_count - 1
                            ),
                            updated_at = NOW()
                        WHERE endpoint_name = ANY(:names)
                        """
                    ),
                    {"names": shared_endpoints},
                )
                return True
            endpoint = (
                (
                    await session.execute(
                        text(
                            """
                        SELECT consecutive_invalid_output, cooldown_level,
                               circuit_state
                        FROM travel_relay_endpoint_state
                        WHERE endpoint_name = :name FOR UPDATE
                        """
                        ),
                        {"name": name},
                    )
                )
                .mappings()
                .one()
            )
            invalid_count = int(endpoint["consecutive_invalid_output"])
            cooldown_level = int(endpoint["cooldown_level"])
            prior_circuit = str(endpoint["circuit_state"])
            transient = failure_class in {
                "TRANSPORT",
                "TIMEOUT",
                "RATE_LIMIT",
                "HTTP_5XX",
                "WIRE_INVALID",
            }
            quarantine = failure_class in {"AUTH", "POLICY_REJECTION"}
            if failure_class == "OUTPUT_CONTRACT":
                invalid_count += 1
                transient = invalid_count >= 3
            cooldown_seconds = COOLDOWN_SECONDS[min(cooldown_level, 2)]
            if retry_after_seconds is not None:
                cooldown_seconds = max(cooldown_seconds, int(retry_after_seconds))
            await session.execute(
                text(
                    """
                    UPDATE travel_relay_endpoint_state
                    SET observation_count = observation_count + 1,
                        transport_success_count = transport_success_count + :transport_success_inc,
                        timeout_count = timeout_count + :timeout_inc,
                        auth_policy_rejection_count = auth_policy_rejection_count + :auth_inc,
                        consecutive_invalid_output = :invalid_count,
                        circuit_state = CASE
                            WHEN :quarantine THEN 'QUARANTINED'
                            WHEN circuit_state = 'QUARANTINED' THEN circuit_state
                            WHEN :transient THEN 'OPEN'
                            ELSE circuit_state
                        END,
                        qualification_state = CASE
                            WHEN :quarantine THEN 'UNQUALIFIED'
                            ELSE qualification_state
                        END,
                        cooldown_until = CASE
                            WHEN :transient THEN NOW() + make_interval(secs => :cooldown_seconds)
                            ELSE cooldown_until
                        END,
                        cooldown_level = CASE
                            WHEN :transient THEN LEAST(2, cooldown_level + 1)
                            ELSE cooldown_level
                        END,
                        updated_at = NOW()
                    WHERE endpoint_name = :name
                    """
                ),
                {
                    "name": name,
                    "transport_success_inc": 1 if transport_succeeded else 0,
                    "timeout_inc": 1 if failure_class == "TIMEOUT" else 0,
                    "auth_inc": 1 if quarantine else 0,
                    "invalid_count": invalid_count,
                    "quarantine": quarantine,
                    "transient": transient,
                    "cooldown_seconds": cooldown_seconds,
                },
            )
            next_circuit = (
                "QUARANTINED"
                if quarantine or prior_circuit == "QUARANTINED"
                else "OPEN"
                if transient
                else prior_circuit
            )
            if next_circuit != prior_circuit:
                logger.warning(
                    "writer_relay_circuit_transition endpoint=%s from=%s to=%s class=%s cooldown_seconds=%s",
                    name,
                    prior_circuit,
                    next_circuit,
                    failure_class,
                    cooldown_seconds if transient else 0,
                )
            return False

    async def finalize_policy_rejection(self, dispatch_id: uuid.UUID) -> None:
        """Apply one deferred endpoint-policy failure exactly once."""
        async with self._session_factory() as session, session.begin():
            row = (
                (
                    await session.execute(
                        text(
                            """
                            UPDATE travel_writer_dispatch
                            SET safe_failure_class = 'POLICY_REJECTION_APPLIED',
                                updated_at = NOW()
                            WHERE dispatch_id = :dispatch_id
                              AND safe_failure_class = 'POLICY_REJECTION'
                            RETURNING endpoint_name
                            """
                        ),
                        {"dispatch_id": dispatch_id},
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                return
            name = str(row["endpoint_name"])
            await session.execute(
                text(
                    """
                    UPDATE travel_relay_endpoint_state
                    SET observation_count = observation_count + 1,
                        auth_policy_rejection_count = auth_policy_rejection_count + 1,
                        pending_policy_count = GREATEST(0, pending_policy_count - 1),
                        circuit_state = 'QUARANTINED',
                        qualification_state = 'UNQUALIFIED',
                        updated_at = NOW()
                    WHERE endpoint_name = :name
                    """
                ),
                {"name": name},
            )
            logger.warning(
                "writer_relay_circuit_transition endpoint=%s to=QUARANTINED class=POLICY_REJECTION",
                name,
            )

    async def list_endpoints(self) -> list[dict[str, Any]]:
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    """
                    SELECT s.endpoint_name, s.participation, s.circuit_state,
                           s.qualification_state, s.max_inflight, s.routing_weight,
                           s.selection_count, s.peak_inflight, s.observation_count,
                           s.transport_success_count, s.timeout_count,
                           s.auth_policy_rejection_count, s.contract_valid_count,
                           s.pending_policy_count, s.cooldown_until,
                           s.operator_actor, s.operator_reason,
                           s.operator_updated_at,
                           COUNT(d.dispatch_id) FILTER (
                               WHERE d.state IN ('CLAIMED', 'DISPATCHED')
                                 AND d.lease_expires_at > NOW()
                           ) AS inflight
                    FROM travel_relay_endpoint_state s
                    LEFT JOIN travel_writer_dispatch d
                      ON d.endpoint_name = s.endpoint_name
                    GROUP BY s.endpoint_name
                    ORDER BY s.endpoint_name
                    """
                )
            )
            rows = [dict(row) for row in result.mappings()]
            participating = [
                row for row in rows if row["endpoint_name"] in PARTICIPATING_ENDPOINTS
            ]
            total_weight = sum(int(row["routing_weight"]) for row in participating)
            total_selected = sum(int(row["selection_count"]) for row in participating)
            for row in participating:
                target = (
                    int(row["routing_weight"]) / total_weight if total_weight else 0.0
                )
                actual = (
                    int(row["selection_count"]) / total_selected
                    if total_selected
                    else 0.0
                )
                row["target_share"] = target
                row["actual_share"] = actual
                row["share_drift"] = actual - target
            return rows

    async def mutate_endpoint(
        self,
        name: str,
        action: str,
        *,
        actor: str,
        reason: str,
        owner_override: bool = False,
    ) -> None:
        if not actor.strip() or not reason.strip():
            raise ValueError("actor and reason are required")
        name = name.strip().lower()
        if owner_override and action != "promote":
            raise ValueError("owner override is valid only for promote")
        async with self._session_factory() as session, session.begin():
            row = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM travel_relay_endpoint_state WHERE endpoint_name = :name FOR UPDATE"
                        ),
                        {"name": name},
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                raise ValueError(f"unknown endpoint: {name}")
            updates: dict[str, Any]
            if action == "disable":
                updates = {"participation": "DISABLED"}
            elif action == "qualify":
                updates = {
                    "qualification_state": "QUALIFIED",
                    "circuit_state": "CLOSED",
                }
            elif action == "promote":
                active_rates = []
                if not owner_override:
                    for active in await self.list_endpoints():
                        if (
                            active["participation"] == "ACTIVE"
                            and active["observation_count"]
                        ):
                            active_rates.append(
                                active["contract_valid_count"]
                                / active["observation_count"]
                            )
                _validate_promotion(
                    name,
                    row,
                    active_rates=active_rates,
                    owner_override=owner_override,
                )
                updates = {
                    "participation": "ACTIVE",
                    "previous_participation": "ACTIVE",
                }
            else:
                raise ValueError(f"unsupported endpoint action: {action}")
            assignments = ", ".join(f"{key} = :{key}" for key in updates)
            await session.execute(
                text(
                    f"""
                    UPDATE travel_relay_endpoint_state
                    SET {assignments}, operator_actor = :actor,
                        operator_reason = :reason, operator_updated_at = NOW(),
                        updated_at = NOW()
                    WHERE endpoint_name = :name
                    """
                ),
                {
                    "name": name,
                    "actor": actor[:128],
                    "reason": (
                        f"[OWNER_OVERRIDE] {reason}" if owner_override else reason
                    )[:500],
                    **updates,
                },
            )
            if owner_override:
                logger.warning(
                    "writer_relay_owner_override endpoint=%s actor=%s reason=%s",
                    name,
                    actor[:128],
                    reason[:500],
                )

    async def claim_probe(
        self,
        name: str,
        owner: str,
        *,
        actor: str = "",
        reason: str = "",
        lease_seconds: int = 60,
    ) -> bool:
        async with self._session_factory() as session, session.begin():
            result = await session.execute(
                text(
                    """
                    UPDATE travel_relay_endpoint_state
                    SET probe_owner = :owner,
                        probe_lease_expires_at = NOW() + make_interval(secs => :lease_seconds),
                        operator_actor = NULLIF(:actor, ''),
                        operator_reason = NULLIF(:reason, ''),
                        operator_updated_at = NOW(),
                        updated_at = NOW()
                    WHERE endpoint_name = :name
                      AND (probe_lease_expires_at IS NULL OR probe_lease_expires_at <= NOW())
                      AND (cooldown_until IS NULL OR cooldown_until <= NOW())
                    RETURNING endpoint_name
                    """
                ),
                {
                    "name": name.lower(),
                    "owner": owner[:128],
                    "actor": actor[:128],
                    "reason": reason[:500],
                    "lease_seconds": lease_seconds,
                },
            )
            return result.first() is not None

    async def finish_probe(self, name: str, owner: str, *, success: bool) -> None:
        async with self._session_factory() as session, session.begin():
            await session.execute(
                text(
                    """
                    UPDATE travel_relay_endpoint_state
                    SET circuit_state = CASE WHEN :success THEN 'CLOSED' ELSE 'OPEN' END,
                        participation = CASE WHEN :success THEN previous_participation ELSE participation END,
                        cooldown_until = CASE
                            WHEN :success THEN NULL
                            ELSE NOW() + make_interval(
                                secs => CASE cooldown_level
                                    WHEN 0 THEN 60
                                    WHEN 1 THEN 120
                                    ELSE 300
                                END
                            )
                        END,
                        cooldown_level = CASE
                            WHEN :success THEN 0
                            ELSE LEAST(2, cooldown_level + 1)
                        END,
                        probe_owner = NULL, probe_lease_expires_at = NULL,
                        updated_at = NOW()
                    WHERE endpoint_name = :name AND probe_owner = :owner
                    """
                ),
                {
                    "name": name.lower(),
                    "owner": owner[:128],
                    "success": success,
                },
            )


@dataclass
class _MemoryEndpoint:
    participation: str
    cap: int
    weight: int
    fingerprint: str = ""
    qualification: str = "QUALIFIED"
    circuit: str = "CLOSED"
    current: int = 0
    selected: int = 0
    invalid: int = 0
    observations: int = 0
    transport_success: int = 0
    timeouts: int = 0
    auth_policy: int = 0
    contract_valid: int = 0
    pending_policy: int = 0
    probe_owner: str | None = None
    probe_until: datetime | None = None
    cooldown_level: int = 0
    cooldown_until: datetime | None = None


@dataclass
class _MemoryDispatch:
    dispatch_id: uuid.UUID
    logical_call_id: uuid.UUID
    ordinal: int
    endpoint: str
    state: str
    lease_expires_at: datetime
    failure_signature: str | None = None
    failure_class: str | None = None


class InMemoryWriterRelayStore:
    """Deterministic non-network store for local fake-traffic acceptance only."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self.endpoints = {
            name: _MemoryEndpoint(participation, cap, weight)
            for name, (participation, cap, weight) in FROZEN_ENDPOINT_POLICY.items()
        }
        self.dispatches: dict[uuid.UUID, _MemoryDispatch] = {}
        self.by_ordinal: dict[tuple[uuid.UUID, int], uuid.UUID] = {}
        self.peak_inflight = {name: 0 for name in self.endpoints}
        self.force_initial: str | None = None

    async def synchronize_endpoints(self, fingerprints: dict[str, str]) -> None:
        async with self._lock:
            for name, fingerprint in fingerprints.items():
                endpoint = self.endpoints[name]
                if endpoint.fingerprint and endpoint.fingerprint != fingerprint:
                    endpoint.qualification = "UNQUALIFIED"
                    endpoint.circuit = "QUARANTINED"
                endpoint.fingerprint = fingerprint

    def _reap(self, now: datetime) -> None:
        for dispatch in self.dispatches.values():
            if (
                dispatch.state in {"CLAIMED", "DISPATCHED"}
                and dispatch.lease_expires_at <= now
            ):
                if dispatch.state == "DISPATCHED":
                    dispatch.state = "OUTCOME_UNKNOWN"
                    if dispatch.failure_class is None:
                        dispatch.failure_class = "PROCESS_LOSS"
                else:
                    dispatch.state = "FAILED"
                    dispatch.failure_class = "CLAIM_EXPIRED"

    def _inflight(self, name: str, now: datetime) -> int:
        return sum(
            1
            for dispatch in self.dispatches.values()
            if dispatch.endpoint == name
            and dispatch.state in {"CLAIMED", "DISPATCHED"}
            and dispatch.lease_expires_at > now
        )

    async def claim(self, **kwargs) -> DispatchClaim:
        now = kwargs.get("now") or _utcnow()
        logical_call_id = kwargs["logical_call_id"]
        ordinal = int(kwargs["ordinal"])
        fingerprints = kwargs["fingerprints"]
        initial = bool(kwargs["initial"])
        excluded = kwargs["exclude_endpoints"]
        async with self._lock:
            self._reap(now)
            key = (logical_call_id, ordinal)
            if key in self.by_ordinal:
                existing = self.dispatches[self.by_ordinal[key]]
                return DispatchClaim(
                    "DUPLICATE", existing.endpoint, existing.dispatch_id
                )
            snapshot = tuple(
                EndpointCapacity(
                    name,
                    endpoint.participation,
                    endpoint.circuit,
                    self._inflight(name, now),
                    endpoint.cap,
                    endpoint.pending_policy,
                )
                for name, endpoint in self.endpoints.items()
                if name in fingerprints
            )
            eligible = []
            for name, endpoint in self.endpoints.items():
                if name not in fingerprints or name in excluded:
                    continue
                if endpoint.participation not in (
                    {"ACTIVE", "CANARY"} if initial else {"ACTIVE"}
                ):
                    continue
                if (
                    endpoint.qualification != "QUALIFIED"
                    or endpoint.circuit != "CLOSED"
                    or endpoint.pending_policy > 0
                ):
                    continue
                if endpoint.fingerprint != fingerprints[name]:
                    continue
                eligible.append((name, endpoint))
            if not eligible:
                return DispatchClaim("UNAVAILABLE", snapshot=snapshot)
            free = [
                pair for pair in eligible if self._inflight(pair[0], now) < pair[1].cap
            ]
            if not free:
                return DispatchClaim("BUSY", snapshot=snapshot)
            forced = self.force_initial if initial else None
            if forced and any(name == forced for name, _endpoint in free):
                name, endpoint = next(pair for pair in free if pair[0] == forced)
                self.force_initial = None
            else:
                total = sum(endpoint.weight for _name, endpoint in free)
                for _name, candidate in free:
                    candidate.current += candidate.weight
                name, endpoint = max(free, key=lambda pair: (pair[1].current, pair[0]))
                endpoint.current -= total
            endpoint.selected += 1
            dispatch_id = uuid.uuid4()
            dispatch = _MemoryDispatch(
                dispatch_id,
                logical_call_id,
                ordinal,
                name,
                "CLAIMED",
                now + timedelta(seconds=float(kwargs["lease_seconds"])),
            )
            self.dispatches[dispatch_id] = dispatch
            self.by_ordinal[key] = dispatch_id
            inflight = self._inflight(name, now)
            self.peak_inflight[name] = max(self.peak_inflight[name], inflight)
            return DispatchClaim("CLAIMED", name, dispatch_id, snapshot)

    async def mark_dispatched(self, dispatch_id: uuid.UUID) -> None:
        async with self._lock:
            dispatch = self.dispatches[dispatch_id]
            if dispatch.state == "CLAIMED":
                dispatch.state = "DISPATCHED"

    async def complete_success(
        self, dispatch_id: uuid.UUID, *, latency_ms: int
    ) -> None:
        del latency_ms
        async with self._lock:
            dispatch = self.dispatches[dispatch_id]
            if dispatch.state == "DISPATCHED":
                dispatch.state = "SUCCEEDED"
                endpoint = self.endpoints[dispatch.endpoint]
                endpoint.observations += 1
                endpoint.transport_success += 1
                endpoint.contract_valid += 1
                endpoint.invalid = 0

    async def complete_failure(self, dispatch_id: uuid.UUID, **kwargs) -> bool:
        async with self._lock:
            dispatch = self.dispatches[dispatch_id]
            if dispatch.state not in {"CLAIMED", "DISPATCHED"}:
                return False
            release_capacity = bool(kwargs.get("release_capacity", True))
            failure_class = kwargs["failure_class"]
            if not release_capacity and failure_class != "TIMEOUT":
                raise ValueError(
                    "release_capacity=False is reserved for probe TIMEOUT"
                )
            if not release_capacity:
                if (
                    dispatch.state != "DISPATCHED"
                    or dispatch.failure_class is not None
                ):
                    return False
            else:
                dispatch.state = "FAILED"
            dispatch.failure_signature = kwargs.get("failure_signature")
            dispatch.failure_class = failure_class
            signature = dispatch.failure_signature
            if failure_class == "POLICY_REJECTION" and signature:
                endpoint = self.endpoints[dispatch.endpoint]
                endpoint.pending_policy += 1
                shared = {
                    item.endpoint
                    for item in self.dispatches.values()
                    if item.logical_call_id == dispatch.logical_call_id
                    and item.failure_signature == signature
                    and item.failure_class == "POLICY_REJECTION"
                }
                if len(shared) < 2:
                    return False
                for item in self.dispatches.values():
                    if (
                        item.logical_call_id == dispatch.logical_call_id
                        and item.failure_signature == signature
                        and item.failure_class == "POLICY_REJECTION"
                    ):
                        item.failure_class = "SHARED_REQUEST_CONTRACT"
                for name in shared:
                    shared_endpoint = self.endpoints[name]
                    shared_endpoint.pending_policy = max(
                        0, shared_endpoint.pending_policy - 1
                    )
                return True
            endpoint = self.endpoints[dispatch.endpoint]
            endpoint.observations += 1
            if kwargs.get("transport_succeeded"):
                endpoint.transport_success += 1
            if failure_class == "OUTPUT_CONTRACT":
                endpoint.invalid += 1
                if endpoint.invalid >= 3:
                    endpoint.circuit = "OPEN"
            elif failure_class in {"AUTH", "POLICY_REJECTION"}:
                endpoint.auth_policy += 1
                endpoint.circuit = "QUARANTINED"
                endpoint.qualification = "UNQUALIFIED"
            elif failure_class in {
                "TRANSPORT",
                "TIMEOUT",
                "RATE_LIMIT",
                "HTTP_5XX",
                "WIRE_INVALID",
            }:
                if endpoint.circuit != "QUARANTINED":
                    endpoint.circuit = "OPEN"
                endpoint.cooldown_until = _utcnow() + timedelta(
                    seconds=COOLDOWN_SECONDS[min(endpoint.cooldown_level, 2)]
                )
                endpoint.cooldown_level = min(2, endpoint.cooldown_level + 1)
                if failure_class == "TIMEOUT":
                    endpoint.timeouts += 1
            return False

    async def finalize_policy_rejection(self, dispatch_id: uuid.UUID) -> None:
        async with self._lock:
            dispatch = self.dispatches[dispatch_id]
            if dispatch.failure_class != "POLICY_REJECTION":
                return
            dispatch.failure_class = "POLICY_REJECTION_APPLIED"
            endpoint = self.endpoints[dispatch.endpoint]
            endpoint.pending_policy = max(0, endpoint.pending_policy - 1)
            endpoint.observations += 1
            endpoint.auth_policy += 1
            endpoint.circuit = "QUARANTINED"
            endpoint.qualification = "UNQUALIFIED"

    async def claim_probe(
        self,
        name: str,
        owner: str,
        *,
        actor: str = "",
        reason: str = "",
        lease_seconds: int = 60,
        now=None,
    ) -> bool:
        del actor, reason
        now = now or _utcnow()
        async with self._lock:
            endpoint = self.endpoints[name]
            if endpoint.probe_until and endpoint.probe_until > now:
                return False
            if endpoint.cooldown_until and endpoint.cooldown_until > now:
                return False
            endpoint.probe_owner = owner
            endpoint.probe_until = now + timedelta(seconds=lease_seconds)
            return True

    async def finish_probe(self, name: str, owner: str, *, success: bool) -> None:
        async with self._lock:
            endpoint = self.endpoints[name]
            if endpoint.probe_owner != owner:
                return
            if success:
                endpoint.circuit = "CLOSED"
                endpoint.cooldown_level = 0
                endpoint.cooldown_until = None
            else:
                endpoint.circuit = "OPEN"
                endpoint.cooldown_until = _utcnow() + timedelta(
                    seconds=COOLDOWN_SECONDS[min(endpoint.cooldown_level, 2)]
                )
                endpoint.cooldown_level = min(2, endpoint.cooldown_level + 1)
            endpoint.probe_owner = None
            endpoint.probe_until = None
