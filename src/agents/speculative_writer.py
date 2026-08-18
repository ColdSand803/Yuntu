"""Typed speculative Writer execution and identity-precedence adjudication.

Transport remains owned by the ordinary Writer relay path and the independent
DS client.  This module races their *typed* results, applies design §8.4 as a
closed truth table, and exposes only the two cancellations authorized by §6.2.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Generic, TypeVar

from src.agents.llm import SpeculativeDSWriterResponse, call_speculative_ds_writer

logger = logging.getLogger(__name__)

DraftT = TypeVar("DraftT")


class OpusAdjudicationState(str, Enum):
    VALID = "valid"
    INVALID = "invalid"
    DEAD = "dead"
    CANCELLED_BUDGET = "cancelled_budget"


class DSAdjudicationState(str, Enum):
    VALID = "valid"
    INVALID = "invalid"
    FAILED = "failed"
    CANCELLED_OPUS_WIN = "cancelled_opus_win"
    CANCELLED_BUDGET = "cancelled_budget"


class AdjudicationReason(str, Enum):
    OPUS_OK = "opus_ok"
    OPUS_REJECTED_DS_ADOPTED = "opus_rejected_ds_adopted"
    OPUS_DEAD_DS_ADOPTED = "opus_dead_ds_adopted"
    DUAL_STRUCTURAL_REJECTION = "dual_structural_rejection"
    OPUS_REJECTED_DS_FAILED = "opus_rejected_ds_failed"
    OPUS_DEAD_DS_REJECTED = "opus_dead_ds_rejected"
    DUAL_PROVIDER_FAILURE = "dual_provider_failure"
    OPUS_REJECTED_DS_CANCELLED = "opus_rejected_ds_cancelled"
    OPUS_DEAD_DS_CANCELLED = "opus_dead_ds_cancelled"
    BUDGET_CUTOFF_DS_ADOPTED = "budget_cutoff_ds_adopted"
    BUDGET_CUTOFF_DS_REJECTED = "budget_cutoff_ds_rejected"
    BUDGET_CUTOFF_DS_FAILED = "budget_cutoff_ds_failed"
    BUDGET_CUTOFF_NO_DRAFT = "budget_cutoff_no_draft"


class AdoptedGenerator(str, Enum):
    OPUS = "opus"
    DS_FLASH = "ds_flash"
    SAFE = "safe"


class ReviewPolicy(str, Enum):
    OPUS_V095 = "opus_v095"
    MANDATORY_FULL = "mandatory_full"
    NONE = "none"


class AlertOwner(str, Enum):
    ALGORITHM = "algorithm"
    OPERATIONS = "operations"


@dataclass(frozen=True)
class ProbeKillObservation:
    endpoint: str
    kind: str
    partial_output_before_kill: bool
    observed_at_monotonic: float


@dataclass(frozen=True)
class SpeculativeTelemetrySnapshot:
    opus_first_token_ms: int | None
    opus_final_ms: int | None
    ds_final_ms: int | None
    adjudicated_at_ms: int | None
    probe_kill_count: int
    probe_kill_endpoints: tuple[str, ...]
    probe_kill_kind: str | None
    probe_partial_output_before_kill: bool | None


@dataclass
class SpeculativeTelemetry:
    """In-memory timeline/probe collector; no draft bodies are stored here."""

    started_monotonic: float | None = None
    opus_first_token_monotonic: float | None = None
    opus_final_monotonic: float | None = None
    ds_final_monotonic: float | None = None
    adjudicated_monotonic: float | None = None
    probe_kills: list[ProbeKillObservation] = field(default_factory=list)

    def start(self, observed_at_monotonic: float) -> None:
        self.started_monotonic = float(observed_at_monotonic)

    def record_opus_first_token(self, observed_at_monotonic: float) -> None:
        if self.opus_first_token_monotonic is None:
            self.opus_first_token_monotonic = float(observed_at_monotonic)

    def record_probe_kill(
        self,
        *,
        endpoint: str,
        kind: str,
        partial_output_before_kill: bool,
        observed_at_monotonic: float,
    ) -> None:
        if kind not in {"first_token", "stall"}:
            return
        self.probe_kills.append(ProbeKillObservation(
            endpoint=str(endpoint),
            kind=kind,
            partial_output_before_kill=bool(partial_output_before_kill),
            observed_at_monotonic=float(observed_at_monotonic),
        ))

    def mark_opus_final(self, observed_at_monotonic: float) -> None:
        if self.opus_final_monotonic is None:
            self.opus_final_monotonic = float(observed_at_monotonic)

    def mark_ds_final(self, observed_at_monotonic: float) -> None:
        if self.ds_final_monotonic is None:
            self.ds_final_monotonic = float(observed_at_monotonic)

    def mark_adjudicated(self, observed_at_monotonic: float) -> None:
        self.adjudicated_monotonic = float(observed_at_monotonic)

    def snapshot(self) -> SpeculativeTelemetrySnapshot:
        def elapsed(observed_at: float | None) -> int | None:
            if self.started_monotonic is None or observed_at is None:
                return None
            return max(0, int((observed_at - self.started_monotonic) * 1000))

        last_kill = self.probe_kills[-1] if self.probe_kills else None
        return SpeculativeTelemetrySnapshot(
            opus_first_token_ms=elapsed(self.opus_first_token_monotonic),
            opus_final_ms=elapsed(self.opus_final_monotonic),
            ds_final_ms=elapsed(self.ds_final_monotonic),
            adjudicated_at_ms=elapsed(self.adjudicated_monotonic),
            probe_kill_count=len(self.probe_kills),
            probe_kill_endpoints=tuple(item.endpoint for item in self.probe_kills),
            probe_kill_kind=last_kill.kind if last_kill is not None else None,
            probe_partial_output_before_kill=(
                last_kill.partial_output_before_kill
                if last_kill is not None
                else None
            ),
        )


@dataclass(frozen=True)
class AdjudicationDecision:
    reason: AdjudicationReason
    opus_state: OpusAdjudicationState
    ds_state: DSAdjudicationState
    adopted: AdoptedGenerator
    review_policy: ReviewPolicy
    alert_owner: AlertOwner | None


def adjudicate(
    opus_state: OpusAdjudicationState,
    ds_state: DSAdjudicationState,
) -> AdjudicationDecision:
    """Apply the 13-row design §8.4 table without inferred wildcards."""
    if opus_state is OpusAdjudicationState.VALID:
        return AdjudicationDecision(
            AdjudicationReason.OPUS_OK,
            opus_state,
            ds_state,
            AdoptedGenerator.OPUS,
            ReviewPolicy.OPUS_V095,
            None,
        )

    rows = {
        (OpusAdjudicationState.INVALID, DSAdjudicationState.VALID): (
            AdjudicationReason.OPUS_REJECTED_DS_ADOPTED,
            AdoptedGenerator.DS_FLASH,
            ReviewPolicy.MANDATORY_FULL,
            AlertOwner.ALGORITHM,
        ),
        (OpusAdjudicationState.DEAD, DSAdjudicationState.VALID): (
            AdjudicationReason.OPUS_DEAD_DS_ADOPTED,
            AdoptedGenerator.DS_FLASH,
            ReviewPolicy.MANDATORY_FULL,
            AlertOwner.OPERATIONS,
        ),
        (OpusAdjudicationState.INVALID, DSAdjudicationState.INVALID): (
            AdjudicationReason.DUAL_STRUCTURAL_REJECTION,
            AdoptedGenerator.SAFE,
            ReviewPolicy.NONE,
            AlertOwner.ALGORITHM,
        ),
        (OpusAdjudicationState.INVALID, DSAdjudicationState.FAILED): (
            AdjudicationReason.OPUS_REJECTED_DS_FAILED,
            AdoptedGenerator.SAFE,
            ReviewPolicy.NONE,
            AlertOwner.ALGORITHM,
        ),
        (OpusAdjudicationState.DEAD, DSAdjudicationState.INVALID): (
            AdjudicationReason.OPUS_DEAD_DS_REJECTED,
            AdoptedGenerator.SAFE,
            ReviewPolicy.NONE,
            AlertOwner.ALGORITHM,
        ),
        (OpusAdjudicationState.DEAD, DSAdjudicationState.FAILED): (
            AdjudicationReason.DUAL_PROVIDER_FAILURE,
            AdoptedGenerator.SAFE,
            ReviewPolicy.NONE,
            AlertOwner.OPERATIONS,
        ),
        (OpusAdjudicationState.INVALID, DSAdjudicationState.CANCELLED_BUDGET): (
            AdjudicationReason.OPUS_REJECTED_DS_CANCELLED,
            AdoptedGenerator.SAFE,
            ReviewPolicy.NONE,
            AlertOwner.ALGORITHM,
        ),
        (OpusAdjudicationState.DEAD, DSAdjudicationState.CANCELLED_BUDGET): (
            AdjudicationReason.OPUS_DEAD_DS_CANCELLED,
            AdoptedGenerator.SAFE,
            ReviewPolicy.NONE,
            AlertOwner.OPERATIONS,
        ),
        (OpusAdjudicationState.CANCELLED_BUDGET, DSAdjudicationState.VALID): (
            AdjudicationReason.BUDGET_CUTOFF_DS_ADOPTED,
            AdoptedGenerator.DS_FLASH,
            ReviewPolicy.MANDATORY_FULL,
            None,
        ),
        (OpusAdjudicationState.CANCELLED_BUDGET, DSAdjudicationState.INVALID): (
            AdjudicationReason.BUDGET_CUTOFF_DS_REJECTED,
            AdoptedGenerator.SAFE,
            ReviewPolicy.NONE,
            AlertOwner.ALGORITHM,
        ),
        (OpusAdjudicationState.CANCELLED_BUDGET, DSAdjudicationState.FAILED): (
            AdjudicationReason.BUDGET_CUTOFF_DS_FAILED,
            AdoptedGenerator.SAFE,
            ReviewPolicy.NONE,
            AlertOwner.OPERATIONS,
        ),
        (
            OpusAdjudicationState.CANCELLED_BUDGET,
            DSAdjudicationState.CANCELLED_BUDGET,
        ): (
            AdjudicationReason.BUDGET_CUTOFF_NO_DRAFT,
            AdoptedGenerator.SAFE,
            ReviewPolicy.NONE,
            AlertOwner.OPERATIONS,
        ),
    }
    try:
        reason, adopted, review_policy, alert_owner = rows[(opus_state, ds_state)]
    except KeyError as exc:
        raise ValueError(
            f"coordinate is outside design §8.4: {opus_state.value}/{ds_state.value}"
        ) from exc
    return AdjudicationDecision(
        reason,
        opus_state,
        ds_state,
        adopted,
        review_policy,
        alert_owner,
    )


@dataclass(frozen=True)
class OpusDraftResult(Generic[DraftT]):
    state: OpusAdjudicationState
    draft: DraftT | None = None
    failure_type: str = ""
    raw_text: str | None = None
    latency_ms: int = 0
    token_in: int = 0
    token_out: int = 0
    prompt_version: str = "opus_v4"

    def __post_init__(self) -> None:
        if (self.state is OpusAdjudicationState.VALID) != (self.draft is not None):
            raise ValueError("only a valid Opus result may carry a draft")
        if (
            self.state
            in {
                OpusAdjudicationState.DEAD,
                OpusAdjudicationState.CANCELLED_BUDGET,
            }
            and self.raw_text is not None
        ):
            raise ValueError("dead or cancelled Opus result cannot carry a draft body")


@dataclass(frozen=True)
class SpeculativeExecutionResult(Generic[DraftT]):
    decision: AdjudicationDecision
    adopted_draft: DraftT | None
    opus_result: OpusDraftResult[DraftT]
    ds_result: DSStandbyResult[DraftT]
    opus_retry_used: bool = False
    completed_opus_results: tuple[OpusDraftResult[DraftT], ...] = ()
    telemetry: SpeculativeTelemetrySnapshot | None = None


class DSTerminalState(str, Enum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED_BY_OPUS_WIN = "CANCELLED_BY_OPUS_WIN"
    CANCELLED_BY_BUDGET_CUTOFF = "CANCELLED_BY_BUDGET_CUTOFF"


@dataclass(frozen=True)
class DSStandbyResult(Generic[DraftT]):
    terminal_state: DSTerminalState
    draft: DraftT | None = None
    raw_text: str | None = None
    structurally_valid: bool = False
    latency_ms: int = 0
    token_in: int = 0
    token_out: int = 0
    model: str = ""
    prompt_version: str = "flash_v3"
    failure_type: str = ""

    def __post_init__(self) -> None:
        if self.terminal_state is DSTerminalState.COMPLETED:
            if self.raw_text is None:
                raise ValueError("COMPLETED DS result requires a complete raw body")
            if self.structurally_valid != (self.draft is not None):
                raise ValueError("DS structural result and in-memory draft disagree")
            return
        if self.raw_text is not None or self.draft is not None:
            raise ValueError("failed or cancelled DS result cannot carry a draft body")
        if self.structurally_valid:
            raise ValueError("failed or cancelled DS result cannot be structurally valid")


class DSStandbyTask(Generic[DraftT]):
    """One DS standby task with exactly two named cancellation surfaces."""

    def __init__(
        self,
        *,
        request: Callable[[], Awaitable[SpeculativeDSWriterResponse]],
        validate: Callable[[str], DraftT | None | Awaitable[DraftT | None]],
    ) -> None:
        self._request = request
        self._validate = validate
        self._cancel_state: DSTerminalState | None = None
        self._cancel_lock = asyncio.Lock()
        self._task = asyncio.create_task(self._run())

    @classmethod
    def start(
        cls,
        *,
        user: str,
        temperature: float,
        validate: Callable[[str], DraftT | None | Awaitable[DraftT | None]],
    ) -> DSStandbyTask[DraftT]:
        async def request() -> SpeculativeDSWriterResponse:
            return await call_speculative_ds_writer(
                user,
                temperature=temperature,
            )

        return cls(request=request, validate=validate)

    async def _run(self) -> DSStandbyResult[DraftT]:
        started = time.monotonic_ns()
        try:
            response = await self._request()
        except asyncio.CancelledError:
            if self._cancel_state is None:
                # Direct task cancellation is not a third lifecycle state.
                raise
            return DSStandbyResult(
                terminal_state=self._cancel_state,
                latency_ms=int((time.monotonic_ns() - started) // 1_000_000),
            )
        except Exception as exc:
            logger.warning(
                "speculative_ds_failed error_type=%s",
                exc.__class__.__name__,
            )
            return DSStandbyResult(
                terminal_state=DSTerminalState.FAILED,
                latency_ms=int((time.monotonic_ns() - started) // 1_000_000),
                failure_type=exc.__class__.__name__,
            )

        validation_failure_type = ""
        try:
            validated = self._validate(response.text)
            draft = await validated if inspect.isawaitable(validated) else validated
        except Exception as exc:
            draft = None
            validation_failure_type = exc.__class__.__name__
            logger.warning(
                "speculative_ds_structural_validation_failed error_type=%s",
                validation_failure_type,
            )
        return DSStandbyResult(
            terminal_state=DSTerminalState.COMPLETED,
            draft=draft,
            raw_text=response.text,
            structurally_valid=draft is not None,
            latency_ms=response.latency_ms,
            token_in=response.token_in,
            token_out=response.token_out,
            model=response.model,
            prompt_version=response.prompt_version,
            failure_type=validation_failure_type,
        )

    @property
    def done(self) -> bool:
        return self._task.done()

    async def wait(self) -> DSStandbyResult[DraftT]:
        return await self._task

    async def _cancel(
        self,
        state: DSTerminalState,
    ) -> DSStandbyResult[DraftT]:
        async with self._cancel_lock:
            if not self._task.done() and self._cancel_state is None:
                self._cancel_state = state
                self._task.cancel()
        return await self.wait()

    async def cancel_by_opus_win(self) -> DSStandbyResult[DraftT]:
        return await self._cancel(DSTerminalState.CANCELLED_BY_OPUS_WIN)

    async def cancel_by_budget_cutoff(self) -> DSStandbyResult[DraftT]:
        return await self._cancel(DSTerminalState.CANCELLED_BY_BUDGET_CUTOFF)


def ds_adjudication_state(result: DSStandbyResult[DraftT]) -> DSAdjudicationState:
    if result.terminal_state is DSTerminalState.COMPLETED:
        return (
            DSAdjudicationState.VALID
            if result.structurally_valid
            else DSAdjudicationState.INVALID
        )
    if result.terminal_state is DSTerminalState.FAILED:
        return DSAdjudicationState.FAILED
    if result.terminal_state is DSTerminalState.CANCELLED_BY_OPUS_WIN:
        return DSAdjudicationState.CANCELLED_OPUS_WIN
    return DSAdjudicationState.CANCELLED_BUDGET


class SpeculativeWriterExecutor(Generic[DraftT]):
    """Race typed draft results while preserving Opus identity precedence."""

    def __init__(
        self,
        *,
        run_opus_initial: Callable[[], Awaitable[OpusDraftResult[DraftT]]],
        run_opus_retry: Callable[[], Awaitable[OpusDraftResult[DraftT]]],
        start_ds: Callable[[], DSStandbyTask[DraftT]],
        workflow_deadline_monotonic: float,
        residual_reserve_seconds: float,
        opus_attempt_cost_seconds: float,
        review_cost_seconds: float,
        request_opus_budget_cancel: Callable[[], None] | None = None,
        telemetry: SpeculativeTelemetry | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._run_opus_initial = run_opus_initial
        self._run_opus_retry = run_opus_retry
        self._start_ds = start_ds
        self._workflow_deadline = float(workflow_deadline_monotonic)
        self._reserve = float(residual_reserve_seconds)
        self._opus_attempt_cost = float(opus_attempt_cost_seconds)
        self._review_cost = float(review_cost_seconds)
        self._request_opus_budget_cancel = request_opus_budget_cancel
        self._telemetry = telemetry or SpeculativeTelemetry()
        self._monotonic = monotonic

    def _remaining(self) -> float:
        return self._workflow_deadline - self._monotonic()

    def _retry_admitted(self) -> bool:
        return self._remaining() >= (
            self._opus_attempt_cost + self._review_cost + self._reserve
        )

    def _cutoff_delay(self) -> float:
        return max(0.0, self._remaining() - self._review_cost - self._reserve)

    @staticmethod
    def _adopted_draft(
        decision: AdjudicationDecision,
        opus_result: OpusDraftResult[DraftT],
        ds_result: DSStandbyResult[DraftT],
    ) -> DraftT | None:
        if decision.adopted is AdoptedGenerator.OPUS:
            return opus_result.draft
        if decision.adopted is AdoptedGenerator.DS_FLASH:
            return ds_result.draft
        return None

    def _finish(
        self,
        *,
        decision: AdjudicationDecision,
        opus_result: OpusDraftResult[DraftT],
        ds_result: DSStandbyResult[DraftT],
        opus_retry_used: bool,
        completed_opus_results: list[OpusDraftResult[DraftT]],
    ) -> SpeculativeExecutionResult[DraftT]:
        self._telemetry.mark_adjudicated(self._monotonic())
        return SpeculativeExecutionResult(
            decision=decision,
            adopted_draft=self._adopted_draft(
                decision,
                opus_result,
                ds_result,
            ),
            opus_result=opus_result,
            ds_result=ds_result,
            opus_retry_used=opus_retry_used,
            completed_opus_results=tuple(completed_opus_results),
            telemetry=self._telemetry.snapshot(),
        )

    async def execute(self) -> SpeculativeExecutionResult[DraftT]:
        self._telemetry.start(self._monotonic())
        # These two calls are deliberately adjacent: both paths fire at T0.
        opus_task = asyncio.create_task(self._run_opus_initial())
        ds_task = self._start_ds()
        cutoff_task = asyncio.create_task(asyncio.sleep(self._cutoff_delay()))
        opus_result: OpusDraftResult[DraftT] | None = None
        ds_result: DSStandbyResult[DraftT] | None = None
        opus_retry_used = False
        opus_invalid_in_hand = False
        opus_invalid_result_in_hand: OpusDraftResult[DraftT] | None = None
        completed_opus_results: list[OpusDraftResult[DraftT]] = []
        try:
            while True:
                waiters: set[asyncio.Task[object]] = {cutoff_task}
                if opus_result is None:
                    waiters.add(opus_task)
                if ds_result is None:
                    waiters.add(ds_task._task)
                await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)

                # Identity precedence also governs simultaneous completions.
                if opus_result is None and opus_task.done():
                    try:
                        opus_result = await opus_task
                    except asyncio.CancelledError:
                        opus_result = OpusDraftResult(
                            OpusAdjudicationState.CANCELLED_BUDGET
                        )

                    if opus_result.raw_text is not None:
                        completed_opus_results.append(opus_result)

                    if (
                        opus_retry_used
                        and opus_result.state is not OpusAdjudicationState.VALID
                    ):
                        if opus_result.state is not OpusAdjudicationState.INVALID:
                            assert opus_invalid_result_in_hand is not None
                            opus_result = OpusDraftResult(
                                OpusAdjudicationState.INVALID,
                                failure_type=(
                                    opus_result.failure_type
                                    or opus_invalid_result_in_hand.failure_type
                                ),
                                raw_text=opus_invalid_result_in_hand.raw_text,
                                latency_ms=opus_invalid_result_in_hand.latency_ms,
                                token_in=opus_invalid_result_in_hand.token_in,
                                token_out=opus_invalid_result_in_hand.token_out,
                                prompt_version=(
                                    opus_invalid_result_in_hand.prompt_version
                                ),
                            )

                    if (
                        opus_result.state is OpusAdjudicationState.INVALID
                        and not opus_retry_used
                        and self._retry_admitted()
                    ):
                        opus_retry_used = True
                        opus_invalid_in_hand = True
                        opus_invalid_result_in_hand = opus_result
                        opus_task = asyncio.create_task(self._run_opus_retry())
                        opus_result = None
                        continue

                    self._telemetry.mark_opus_final(self._monotonic())

                    if opus_result.state is OpusAdjudicationState.VALID:
                        if ds_result is None:
                            ds_result = (
                                await ds_task.wait()
                                if ds_task.done
                                else await ds_task.cancel_by_opus_win()
                            )
                            self._telemetry.mark_ds_final(self._monotonic())
                        decision = adjudicate(
                            OpusAdjudicationState.VALID,
                            ds_adjudication_state(ds_result),
                        )
                        return self._finish(
                            decision=decision,
                            opus_result=opus_result,
                            ds_result=ds_result,
                            opus_retry_used=opus_retry_used,
                            completed_opus_results=completed_opus_results,
                        )

                if ds_result is None and ds_task.done:
                    ds_result = await ds_task.wait()
                    self._telemetry.mark_ds_final(self._monotonic())

                if opus_result is not None and ds_result is not None:
                    decision = adjudicate(
                        opus_result.state,
                        ds_adjudication_state(ds_result),
                    )
                    return self._finish(
                        decision=decision,
                        opus_result=opus_result,
                        ds_result=ds_result,
                        opus_retry_used=opus_retry_used,
                        completed_opus_results=completed_opus_results,
                    )

                if cutoff_task.done():
                    if opus_result is None:
                        if self._request_opus_budget_cancel is not None:
                            self._request_opus_budget_cancel()
                        opus_task.cancel("CANCELLED_BY_BUDGET_CUTOFF")
                        await asyncio.gather(opus_task, return_exceptions=True)
                        opus_result = (
                            opus_invalid_result_in_hand
                            if opus_invalid_in_hand
                            else OpusDraftResult(
                                OpusAdjudicationState.CANCELLED_BUDGET
                            )
                        )
                        assert opus_result is not None
                        self._telemetry.mark_opus_final(self._monotonic())
                    if ds_result is None:
                        ds_result = await ds_task.cancel_by_budget_cutoff()
                        self._telemetry.mark_ds_final(self._monotonic())
                    decision = adjudicate(
                        opus_result.state,
                        ds_adjudication_state(ds_result),
                    )
                    return self._finish(
                        decision=decision,
                        opus_result=opus_result,
                        ds_result=ds_result,
                        opus_retry_used=opus_retry_used,
                        completed_opus_results=completed_opus_results,
                    )
        except asyncio.CancelledError:
            # The outer workflow deadline is the same budget-cutoff lifecycle.
            if not opus_task.done():
                if self._request_opus_budget_cancel is not None:
                    self._request_opus_budget_cancel()
                opus_task.cancel("CANCELLED_BY_BUDGET_CUTOFF")
            if not ds_task.done:
                await ds_task.cancel_by_budget_cutoff()
            await asyncio.gather(opus_task, return_exceptions=True)
            raise
        finally:
            if not cutoff_task.done():
                cutoff_task.cancel()
            await asyncio.gather(cutoff_task, return_exceptions=True)
