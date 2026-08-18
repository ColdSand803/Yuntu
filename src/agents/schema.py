"""Pydantic schemas for the trip workflow."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from src.cost_estimate.models import CostEstimateSnapshotV1
from src.cost_sources.models import SourceObservation

WorkflowResultType = Literal[
    "PLAN_READY",
    "NO_CANDIDATES",
    "NO_USABLE_ROUTE",
]

RequestedCommuteMode = Literal["driving", "transit", "cycling"]
EffectiveCommuteMode = Literal["driving", "transit", "walking", "cycling"]
TransitStepKind = Literal["walking", "bus", "rail", "other"]
TransitDetailQuality = Literal["complete", "partial", "missing"]

_TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def parse_hhmm(value: str | None) -> int | None:
    if value is None:
        return None
    match = _TIME_PATTERN.fullmatch(value.strip())
    if match is None:
        return None
    return int(match.group(1)) * 60 + int(match.group(2))


class RestWindow(BaseModel):
    """User preferred rest window. v0.8.9 supports only all-day matching."""
    days: str = "all"
    start: str
    end: str

    @field_validator("days")
    @classmethod
    def _validate_days(cls, value: str) -> str:
        days = value.strip()
        if days != "all":
            raise ValueError('rest_windows.days must be "all"')
        return days

    @field_validator("start", "end")
    @classmethod
    def _validate_time(cls, value: str) -> str:
        time_value = value.strip()
        if parse_hhmm(time_value) is None:
            raise ValueError("time must use HH:MM format")
        return time_value

    @model_validator(mode="after")
    def _validate_window(self) -> "RestWindow":
        start = parse_hhmm(self.start)
        end = parse_hhmm(self.end)
        if start is None or end is None:
            return self
        if start >= end:
            raise ValueError("rest_windows.start must be before end")
        duration = end - start
        if duration < 30 or duration > 240:
            raise ValueError("rest window length must be 30 minutes to 4 hours")
        return self


class MustIncludeItem(BaseModel):
    """A user-requested place anchor from structured clients."""
    place_id: int | None = None
    name: str

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("must_include.name must not be empty")
        if len(name) > 100:
            raise ValueError("must_include.name must be at most 100 characters")
        return name


class AccommodationRequest(BaseModel):
    """User-provided accommodation anchor input."""

    name: str | None = None
    place_id: int | None = None
    latitude: float | None = None
    longitude: float | None = None


class AccommodationSuggestion(BaseModel):
    """Resolved accommodation anchor.

    ``name`` may be the placeholder ``用户指定住宿位置`` for coordinate-only
    input. P3 deterministic copy must render that placeholder specially.
    """

    name: str
    latitude: float
    longitude: float
    source: Literal["user_specified", "auto_recommended"]
    reason: str = ""
    user_input_unmatched: str = ""


class TrainOption(BaseModel):
    """One recommended G/D train returned by the runtime provider."""

    train_no: str
    departure_time: str
    arrival_time: str
    duration_minutes: int
    departure_station: str
    arrival_station: str
    second_class_price: float | None = None
    first_class_price: float | None = None


class FlightOption(BaseModel):
    """One recommended scheduled flight."""

    flight_no: str
    airline: str
    departure_time: str
    arrival_time: str
    duration_minutes: int
    departure_airport: str
    arrival_airport: str


class TransportModeSummary(BaseModel):
    """Mode-level intercity transport recommendation."""

    mode: Literal["train", "flight"]
    min_duration_minutes: int
    price_range: str
    price_source: Literal["realtime", "static_reference"]
    daily_count: int
    data_source: Literal["realtime", "static_fallback"]
    availability_status: Literal[
        "available_at_query",
        "sold_out_at_query",
        "unknown",
    ] = "unknown"
    availability_checked_at: str | None = None
    top_options: list[TrainOption] | list[FlightOption] = Field(default_factory=list)


class TransportSuggestion(BaseModel):
    """Optional deterministic intercity recommendation attached to each plan."""

    from_city: str
    to_city: str
    query_date: str | None = None
    modes: list[TransportModeSummary] = Field(default_factory=list)
    source: Literal["realtime", "mixed", "static_fallback"]
    cached_at: str | None = None


class TripRequest(BaseModel):
    """User intent parsed into structured fields."""
    from_city: str = ""
    to_city: str = "重庆"
    start_date: str | None = None
    end_date: str | None = None
    days: int = 3
    people_count: int = 1
    preferences: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    notes: str = ""
    commute_mode: RequestedCommuteMode = "driving"
    must_include: list[MustIncludeItem] = Field(default_factory=list)
    daily_start: str | None = None
    daily_end: str | None = None
    rest_windows: list[RestWindow] = Field(default_factory=list)
    accommodation: AccommodationRequest | None = None

    @field_validator("daily_start", "daily_end")
    @classmethod
    def _validate_daily_time(cls, value: str | None) -> str | None:
        if value is None:
            return None
        time_value = value.strip()
        if parse_hhmm(time_value) is None:
            raise ValueError("time must use HH:MM format")
        return time_value

    @field_validator("must_include", mode="before")
    @classmethod
    def _clean_must_include(cls, value):
        from src.agents.poi_alias import normalize_place_name

        if value is None:
            return []
        if not isinstance(value, list):
            return value
        cleaned = []
        seen: set[str] = set()
        for item in value:
            if isinstance(item, MustIncludeItem):
                raw_name = item.name
                place_id = item.place_id
                raw_item = item.model_dump()
            elif isinstance(item, dict):
                raw_name = item.get("name")
                place_id = item.get("place_id")
                raw_item = dict(item)
            else:
                cleaned.append(item)
                continue
            if not isinstance(raw_name, str):
                cleaned.append(item)
                continue
            name = raw_name.strip()
            if not name:
                continue
            normalized = normalize_place_name(name)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            raw_item["name"] = name
            raw_item["place_id"] = place_id
            cleaned.append(raw_item)
        if len(cleaned) > 5:
            raise ValueError("must_include supports at most 5 items")
        return cleaned

    @model_validator(mode="after")
    def _validate_time_preferences(self) -> "TripRequest":
        if len(self.rest_windows) > 2:
            raise ValueError("rest_windows supports at most 2 windows")
        daily_start = parse_hhmm(self.daily_start)
        daily_end = parse_hhmm(self.daily_end)
        if daily_start is not None and daily_end is not None:
            if daily_start >= daily_end:
                raise ValueError("daily_start must be before daily_end")
            for window in self.rest_windows:
                window_start = parse_hhmm(window.start)
                window_end = parse_hhmm(window.end)
                if (
                    window_start is not None
                    and window_end is not None
                    and (window_start < daily_start or window_end > daily_end)
                ):
                    raise ValueError(
                        "rest_windows must be within daily_start and daily_end"
                    )
        return self

    def has_time_preferences(self) -> bool:
        return bool(self.daily_start or self.daily_end or self.rest_windows)

    def daily_span_minutes(self) -> int | None:
        daily_start = parse_hhmm(self.daily_start)
        daily_end = parse_hhmm(self.daily_end)
        if daily_start is None or daily_end is None:
            return None
        return daily_end - daily_start

    def rest_window_minutes(self) -> int:
        total = 0
        for window in self.rest_windows:
            start = parse_hhmm(window.start)
            end = parse_hhmm(window.end)
            if start is not None and end is not None and end > start:
                total += end - start
        return total

    def time_preferences_payload(self) -> dict | None:
        if not self.has_time_preferences():
            return None
        payload: dict = {}
        if self.daily_start:
            payload["daily_start"] = self.daily_start
        if self.daily_end:
            payload["daily_end"] = self.daily_end
        if self.rest_windows:
            payload["rest_windows"] = [
                window.model_dump()
                for window in self.rest_windows
            ]
        return payload


class CandidatePlace(BaseModel):
    """A canonical place plus optional summary evidence."""
    place_id: int
    canonical_place_id: int | None = None
    name: str
    place_type: str
    district: str | None = None
    category_tags: list[str] = Field(default_factory=list)
    base_priority: int = 0
    typical_visit_minutes: int | None = None
    typical_visit_source: str | None = None
    typical_visit_confidence: float | None = None
    mention_count: int = 0
    positive_count: int = 0
    negative_count: int = 0
    source_count: int = 0
    quality_score: float = 0.0
    recommend_score: float = 0.0
    effective_score: float = 0.0
    longitude: float | None = None
    latitude: float | None = None
    adcode: str | None = None
    amap_poi_id: str | None = None
    amap_rating: str | None = None
    amap_avg_price: str | None = None
    amap_open_time: str | None = None
    top_reasons: list[dict] = Field(default_factory=list)
    warnings: list[dict] = Field(default_factory=list)
    must_include: bool = False


class CandidateGroup(BaseModel):
    """Evidence-backed candidate input for one generated plan."""
    label: str
    internal_theme: str = ""
    candidates: list[CandidatePlace] = Field(default_factory=list)


class RetrievalResult(BaseModel):
    """Output of Data Retrieval agent."""
    city: str
    candidates: list[CandidatePlace]
    route_planning_candidates: list[CandidatePlace] = Field(
        default_factory=list,
        exclude=True,
    )
    evidence_summary: str = ""
    candidate_groups: list[CandidateGroup] = Field(default_factory=list)
    qualified_candidate_count: int = 0
    in_response_candidate_overlap: float | None = None
    diversity_gap: bool = False


class CompositionStop(BaseModel):
    """Writing role for one locked route stop."""
    place_id: int
    name: str
    role: str
    meal_slot: str | None = None
    emphasis: str = "normal"
    writing_hint: str | dict = ""


class CompositionCommute(BaseModel):
    """Writing guidance for one locked commute leg."""
    from_place_id: int
    to_place_id: int
    duration_minutes: int
    mode: EffectiveCommuteMode = "driving"
    style: str
    must_mention: bool = False
    # Short ready-to-copy transition; detailed line/stop truth stays structured.
    transit_transition: str | None = None


class CompositionDay(BaseModel):
    """Composition guidance for one locked travel day."""
    day: int
    theme_code: str
    theme_label: str
    stops: list[CompositionStop] = Field(default_factory=list)
    commutes: list[CompositionCommute] = Field(default_factory=list)
    writing_notes: list[str] = Field(default_factory=list)


class CompositionBlueprint(BaseModel):
    """Deterministic itinerary-composition guidance for one plan."""
    version: str = "v0.6.9"
    plan_label: str
    days: list[CompositionDay] = Field(default_factory=list)


PoiIdentityRelationType = Literal[
    "canonical_same",
    "alias_same",
    "parent_child",
    "nearby_distinct",
    "unknown",
]


class PoiIdentityRelation(BaseModel):
    """Deterministic relationship between a locked POI and another POI name."""
    source_name: str
    target_name: str
    relation: PoiIdentityRelationType
    reason: str = ""


class PoiIdentityResult(BaseModel):
    """POI identity graph used before writing and review."""
    version: str = "v0.6.10"
    plan_label: str
    relations: list[PoiIdentityRelation] = Field(default_factory=list)


BudgetStatus = Literal[
    "within_budget",
    "relaxed_exception",
    "pruned",
    "infeasible",
]


class BudgetDayResult(BaseModel):
    """Commute-budget decision for one locked travel day."""
    day: int
    status: BudgetStatus
    budget_minutes: int
    commute_minutes: int
    overage_ratio: float = 0.0
    removed_place_ids: list[int] = Field(default_factory=list)
    removed_place_names: list[str] = Field(default_factory=list)
    reason: str = ""


class BudgetResult(BaseModel):
    """Budget resolution for one route plan before prose generation."""
    version: str = "v0.6.10"
    plan_label: str
    days: list[BudgetDayResult] = Field(default_factory=list)


class PoiNarrativeFragment(BaseModel):
    """Backend-owned POI prose fragment keyed by locked route identity.

    This registry is internal workflow state.  It gives Gate/Review/Repair an
    immutable ownership key without exposing another frontend response field.
    """

    plan_index: int = Field(ge=1)
    day: int = Field(ge=1)
    place_id: int = Field(ge=1)
    text: str
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    source: Literal[
        "writer",
        "deterministic_completion",
        "deterministic_food_none",
        "fragment_repair",
        "safe_renderer",
    ] = "writer"


class PlanOutput(BaseModel):
    """One generated travel plan."""
    plan_name: str
    plan_text: str
    # Writer-generated whole-trip summary (v0.9.0.1). Empty means "use the
    # deterministic fallback"; old plan_json rows without the field stay valid.
    summary: str = ""
    used_place_ids: list[int] = Field(default_factory=list)
    used_place_names: list[str] = Field(default_factory=list)
    day_place_names: list[list[str]] = Field(default_factory=list)
    composition_blueprint: CompositionBlueprint | None = None
    poi_identity_result: PoiIdentityResult | None = None
    budget_result: BudgetResult | None = None
    accommodation: AccommodationSuggestion | None = None
    transport: TransportSuggestion | None = None
    poi_fragments: list[PoiNarrativeFragment] = Field(
        default_factory=list,
        exclude=True,
    )

    def poi_fragment(
        self,
        *,
        plan_index: int,
        day: int,
        place_id: int,
    ) -> PoiNarrativeFragment | None:
        key = (plan_index, day, place_id)
        return next(
            (
                fragment
                for fragment in self.poi_fragments
                if (
                    fragment.plan_index,
                    fragment.day,
                    fragment.place_id,
                )
                == key
            ),
            None,
        )


class TransitStep(BaseModel):
    """One normalized provider-ordered fact inside a public-transit leg."""
    kind: TransitStepKind
    duration_minutes: int | None = Field(default=None, ge=0)
    distance_meters: int | None = Field(default=None, ge=0)
    line_name: str | None = None
    provider_type: str | None = None
    from_stop: str | None = None
    to_stop: str | None = None
    stop_count: int | None = Field(default=None, ge=1)

    @field_validator(
        "line_name",
        "provider_type",
        "from_stop",
        "to_stop",
        mode="before",
    )
    @classmethod
    def _normalize_nullable_text(cls, value):
        if value is None or not isinstance(value, str):
            return None
        text = value.strip()
        return text or None

    @model_validator(mode="after")
    def _clear_walking_ride_fields(self) -> "TransitStep":
        if self.kind == "walking":
            self.line_name = None
            self.provider_type = None
            self.from_stop = None
            self.to_stop = None
            self.stop_count = None
        return self


class CommuteLeg(BaseModel):
    """One deterministic commute edge in a planned travel day."""
    from_place_id: int
    to_place_id: int
    from_name: str
    to_name: str
    distance_meters: int
    duration_minutes: int
    mode: EffectiveCommuteMode = "driving"
    source: str = "estimate"
    note: str = ""
    encoded_polyline: str = ""
    transit_steps: list[TransitStep] = Field(default_factory=list)
    transit_detail_quality: TransitDetailQuality = "missing"
    # Internal provenance only: true exclusively for a validated detail-v2 hit.
    transit_detail_cache_hit: bool = False
    # Internal P2 fact only. Public projection ignores this field; P3 will
    # consume it before creating the immutable Cost Estimate Snapshot.
    fare_observation: SourceObservation | None = None


class RouteDayGroup(BaseModel):
    """Locked place assignment for one day of one generated plan."""
    day: int
    area: str = ""
    adcode: str | None = None
    places: list[CandidatePlace] = Field(default_factory=list)
    commute_legs: list[CommuteLeg] = Field(default_factory=list)
    commute_minutes: int = 0
    commute_notes: list[str] = Field(default_factory=list)
    time_hints: list[str] = Field(default_factory=list)


class RoutePlan(BaseModel):
    """Deterministic route skeleton for one A/B candidate group."""
    label: str
    day_groups: list[RouteDayGroup] = Field(default_factory=list)
    dropped_place_ids: list[int] = Field(default_factory=list)
    optimized: bool = True
    fallback_reason: str | None = None


PublishedVariant = Literal["normal", "safe"]
DeliveryStatus = Literal["NORMAL", "DEGRADED"]
SafeTrigger = Literal[
    "review_no_anchor",
    "fragment_repair_failed",
    "writer_failure",
    "speculative_no_publishable_draft",
]


class DeliveryMetadata(BaseModel):
    """Authoritative delivery semantics; detailed cause remains internal."""

    published_variant: PublishedVariant = "normal"
    delivery_status: DeliveryStatus = "NORMAL"
    safe_trigger: SafeTrigger | None = None

    @model_validator(mode="after")
    def validate_combination(self) -> "DeliveryMetadata":
        if self.published_variant == "safe":
            if self.delivery_status != "DEGRADED" or self.safe_trigger is None:
                raise ValueError("safe delivery requires DEGRADED and a safe_trigger")
        elif self.safe_trigger is not None:
            raise ValueError("normal delivery cannot carry a safe_trigger")
        return self

    @classmethod
    def from_metrics(cls, metrics: dict[str, Any] | None) -> "DeliveryMetadata":
        values = metrics if isinstance(metrics, dict) else {}
        return cls(
            published_variant=values.get("published_variant", "normal"),
            delivery_status=values.get("delivery_status", "NORMAL"),
            safe_trigger=values.get("safe_trigger"),
        )


class WorkflowResult(BaseModel):
    """Final output of the full trip workflow."""
    trip_request: TripRequest
    plans: list[PlanOutput]
    result_type: WorkflowResultType = "PLAN_READY"
    review_notes: str = ""
    quality_metrics: dict = Field(default_factory=dict)
    delivery_metadata: DeliveryMetadata = Field(default_factory=DeliveryMetadata)
    route_plans: list[RoutePlan] = Field(default_factory=list)
    weather_display: dict = Field(default_factory=dict)
    cost_estimate_snapshots: list[CostEstimateSnapshotV1] = Field(
        default_factory=list,
        exclude=True,
    )
    record_id: int | None = None
