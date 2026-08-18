from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings


_FROZEN_WRITER_STREAM_ATTEMPT_CAP_SECONDS = 60.0
_FROZEN_WORKFLOW_WALL_SECONDS = 180.0


class Settings(BaseSettings):
    app_version: str = "0.9.6"
    database_url: str = "postgresql+asyncpg://user:pass@localhost:5432/yuntu_travel"
    gemini_api_key: str = ""
    tikhub_api_token: str = ""
    tikhub_base_url: str = "https://api.tikhub.io"
    tikhub_rps: float = 5.0
    tikhub_timeout_seconds: float = 30.0
    tikhub_max_retries: int = 3
    yuntu_travel_admin_token: str = ""
    yuntu_travel_internal_credential: str = ""
    yuntu_travel_bff_internal_admin_credential: str = ""
    trip_worker_concurrency: int = 5
    trip_job_timeout_seconds: int = 180
    trip_stale_sweep_interval_seconds: int = 30
    trip_worker_enabled: bool = True
    projection_publisher_enabled: bool = False
    projection_rabbitmq_url: str = ""
    projection_exchange_name: str = "yuntu.admin.trip-projection"
    projection_routing_key: str = "trip.projection.committed"
    projection_heartbeat_interval_seconds: float = 10.0
    projection_publisher_poll_seconds: float = 0.5
    projection_publisher_retry_seconds: float = 2.0
    projection_broker_connect_timeout_seconds: float = 5.0
    projection_publish_confirm_timeout_seconds: float = 5.0
    export_worker_enabled: bool = True
    export_worker_poll_interval_seconds: float = 2.0
    export_storage_dir: str = "/data/yuntu-travel/exports"
    export_artifact_ttl_days: int = 7
    export_pdf_concurrency: int = 4
    export_share_image_concurrency: int = 2
    export_pdf_timeout_seconds: int = 420
    export_share_image_timeout_seconds: int = 420
    export_pdf_daily_ip_limit: int = 5
    export_share_image_daily_ip_limit: int = 100
    export_image_api_base_url: str = ""
    export_image_api_key: str = ""
    export_image_model: str = "gpt-image-2"
    export_image_timeout_seconds: float = 360.0
    export_image_api_mode: str = "chat_completions"
    export_image_size: str = "1024x1536"
    export_image_quality: str = "standard"
    export_image_style: str = "vivid"
    export_image_response_format: str = "b64_json"
    export_image_provider_pool: str = ""
    export_image_provider_max_attempts: int = 2
    export_image_provider_cooldown_seconds: float = 600.0
    public_api_ip_allowlist: str = "127.0.0.1,::1"
    public_api_trust_proxy_headers: bool = False
    crawl_worker_enabled: bool = True
    crawl_subprocess_timeout_seconds: int = 600
    extract_subprocess_timeout_seconds: int = 600
    extract_concurrency: int = 3
    poi_resolve_timeout_seconds: int = 600
    refresh_summary_timeout_seconds: int = 180
    city_batch_worker_enabled: bool = True
    city_batch_timeout_seconds: int = 3600
    city_batch_heartbeat_seconds: int = 30
    city_batch_limit_per_keyword: int = 20
    city_gate_allow_discovered_for_validation: bool = False
    place_demand_enabled: bool = False
    must_include_anchor_enabled: bool = False
    time_preferences_enabled: bool = False
    food_recommendation_enabled: bool = False
    route_quality_selection_enabled: bool = False
    commute_mode_enabled: bool = False
    # v0.9.3 deterministic intercity transport recommendation.
    intercity_transport_enabled: bool = False
    transport_12306_timeout_seconds: float = 5.0
    transport_12306_retry_count: int = 1
    aviation_edge_api_key: str = ""
    transport_flight_timeout_seconds: float = 5.0
    transport_cache_ttl_seconds: int = 900
    transport_station_map_ttl_hours: int = 24
    transport_resolver_total_budget_seconds: float = 12.0
    llm_verify_ssl: bool = True

    # Route Planning / v0.6 data pipeline.
    route_daily_commute_budget_normal: int = 90
    route_daily_commute_budget_relaxed: int = 60
    route_daily_commute_budget_compact: int = 120
    route_single_leg_max: int = 60
    route_single_leg_max_transit: int = 80
    route_single_leg_max_walking: int = 28
    route_single_leg_max_cycling: int = 35
    route_estimate_road_factor: float = 1.5
    commute_walk_switch_max_meters: int = 800
    commute_daily_budget_factor_driving: float = 1.0
    commute_daily_budget_factor_transit: float = 1.5
    commute_daily_budget_factor_walking: float = 1.0
    commute_daily_budget_factor_cycling: float = 1.1
    commute_estimate_speed_kmh_driving: float = 20.0
    commute_estimate_speed_kmh_transit: float = 15.0
    commute_estimate_speed_kmh_walking: float = 4.5
    commute_estimate_speed_kmh_cycling: float = 12.0
    route_places_per_day_min: int = 2
    route_places_per_day_max: int = 5

    amap_api_key: str = ""
    amap_api_key_two: str = ""
    amap_geocode_timeout: float = 5.0
    amap_poi_search_timeout: float = 5.0
    amap_poi_qps: float = 2.0
    amap_route_enabled: bool = True
    amap_route_timeout: float = 5.0
    amap_route_qps: float = 0.5
    amap_route_backoff_seconds: float = 60.0
    amap_route_cache_ttl_hours: int = 72
    amap_route_enrichment_concurrency: int = 2
    amap_route_enrichment_timeout_seconds: float = 120.0
    amap_route_call_budget: int = 24
    amap_route_time_budget_ms: int = 45000
    amap_district_sync_interval_days: int = 90
    weather_enrichment_enabled: bool = False
    amap_weather_api_key: str = ""
    amap_weather_timeout: float = 5.0

    redis_url: str = ""

    # Per-role LLM governance.
    # *_api_key falls back to gemini_api_key when empty (gemini provider only).
    relay_gpt_base_url: str = ""
    relay_gpt_api_key: str = ""
    relay_gpt_wire_api: str = "openai_responses"
    relay_gpt_pool: str = ""
    relay_gpt_extract_base_url: str = ""
    relay_gpt_extract_api_key: str = ""
    relay_gpt_extract_wire_api: str = "openai_responses"
    relay_gpt_extract_pool: str = ""
    relay_gpt_grouping_base_url: str = ""
    relay_gpt_grouping_api_key: str = ""
    relay_gpt_grouping_wire_api: str = "openai_responses"
    relay_gpt_grouping_pool: str = ""
    relay_gpt_review_base_url: str = ""
    relay_gpt_review_api_key: str = ""
    relay_gpt_review_wire_api: str = "openai_responses"
    relay_gpt_review_pool: str = ""
    relay_claude_base_url: str = ""
    relay_claude_api_key: str = ""
    relay_claude_wire_api: str = "anthropic_messages"
    relay_claude_pool: str = ""
    relay_claude_newapi_base_url: str = ""
    relay_claude_newapi_api_key: str = ""
    relay_claude_newapi_wire_api: str = "openai_chat"
    relay_claude_newapi_pool: str = ""
    relay_claude_opus_base_url: str = ""
    relay_claude_opus_api_key: str = ""
    relay_claude_opus_wire_api: str = "openai_chat"
    relay_claude_opus_pool: str = ""
    relay_claude_sonnet_backup_base_url: str = ""
    relay_claude_sonnet_backup_api_key: str = ""
    relay_claude_sonnet_backup_wire_api: str = "openai_chat"
    relay_claude_sonnet_backup_pool: str = ""
    relay_gemini_base_url: str = ""
    relay_gemini_api_key: str = ""
    relay_gemini_wire_api: str = "openai_chat"
    relay_gemini_pool: str = ""
    relay_pool_cooldown_seconds: float = 120.0

    intent_provider: str = "relay"
    intent_relay_profile: str = "gpt"
    intent_model: str = "gpt-5.5"
    intent_api_key: str = ""

    extract_provider: str = "deepseek"
    extract_relay_profile: str = "gpt"
    extract_model: str = "deepseek-v4-flash"
    extract_api_key: str = ""

    writer_provider: str = "relay"
    writer_relay_profile: str = "claude_opus"
    writer_model: str = "claude-opus-4-6"
    writer_api_key: str = ""
    writer_stream_probe_enabled: bool = False
    writer_stream_first_token_deadline_seconds: float = 15.0
    writer_stream_stall_deadline_seconds: float = 10.0
    writer_plan_concurrency_enabled: bool = True
    writer_plan_concurrency_fallback_enabled: bool = True
    writer_repair_concurrency_enabled: bool = True
    writer_repair_max_wall_seconds: float = 120.0
    writer_repair_per_plan_timeout_seconds: float = 90.0
    writer_repair_max_followup_rounds: int = 2
    writer_repair_max_target_plans_per_round: int = 3
    # PostgreSQL endpoint leases are the Writer capacity authority. Zero removes
    # the obsolete process-local bottleneck.
    writer_llm_concurrency: int = 0
    writer_relay_routing_enabled: bool = True
    writer_temperature: float = 1.0
    writer_retry_temperature: float = 0.8
    writer_repair_temperature: float = 0.7
    writer_strict_evidence_mode: str = "auto"
    activity_local_completion_enabled: bool = True
    writer_parse_failure_raw_excerpt_enabled: bool = False
    writer_parse_failure_raw_excerpt_chars: int = 1000

    # v0.9.6 out-of-pool DeepSeek official-API standby role.
    speculative_ds_standby_enabled: bool = False
    speculative_ds_model: str = "deepseek-v4-flash"
    speculative_ds_api_key: str = ""
    speculative_ds_base_url: str = ""
    speculative_ds_timeout_seconds: float = 60.0

    review_provider: str = "relay"
    review_relay_profile: str = "gpt_review"
    review_model: str = "gpt-5.5"
    review_api_key: str = ""
    review_plan_concurrency_enabled: bool = True
    review_llm_concurrency: int = 2
    # v0.8.13 restores the proven v0.8.11.1 low-risk initial Review fast path.
    # Publish Retry and any body that fails a deterministic gate still run Review.
    review_risk_skip_enabled: bool = True
    # v0.9.5 delivery policies are independent from Provider routing. They stay
    # rollout-gated until BFF and Web consumers are deployed together.
    review_unavailable_degraded_enabled: bool = False
    safe_plan_writer_fallback_enabled: bool = False
    safe_plan_review_fallback_enabled: bool = False

    grouping_provider: str = "relay"
    grouping_relay_profile: str = "gpt_grouping"
    grouping_model: str = "gpt-5.5"
    grouping_api_key: str = ""
    grouping_temperature: float = 0.3

    @model_validator(mode="after")
    def _validate_commute_mode_settings(self) -> "Settings":
        if self.trip_job_timeout_seconds <= 0:
            raise ValueError("TRIP_JOB_TIMEOUT_SECONDS must be positive")
        if self.trip_worker_concurrency <= 0:
            raise ValueError("TRIP_WORKER_CONCURRENCY must be positive")
        probe_deadline_fields = (
            "writer_stream_first_token_deadline_seconds",
            "writer_stream_stall_deadline_seconds",
        )
        for field_name in probe_deadline_fields:
            if float(getattr(self, field_name)) <= 0:
                raise ValueError(f"{field_name} must be positive")
        if (
            self.writer_stream_first_token_deadline_seconds
            >= _FROZEN_WRITER_STREAM_ATTEMPT_CAP_SECONDS
        ):
            raise ValueError(
                "WRITER_STREAM_FIRST_TOKEN_DEADLINE_SECONDS must be less than "
                "the frozen 60-second streaming attempt cap"
            )
        if self.speculative_ds_timeout_seconds <= 0:
            raise ValueError("SPECULATIVE_DS_TIMEOUT_SECONDS must be positive")
        effective_workflow_wall_seconds = min(
            float(self.trip_job_timeout_seconds),
            _FROZEN_WORKFLOW_WALL_SECONDS,
        )
        if self.speculative_ds_timeout_seconds > effective_workflow_wall_seconds:
            raise ValueError(
                "SPECULATIVE_DS_TIMEOUT_SECONDS must not exceed "
                "the effective workflow wall"
            )
        if (
            self.speculative_ds_standby_enabled
            and not self.speculative_ds_api_key.strip()
        ):
            raise ValueError(
                "SPECULATIVE_DS_API_KEY is required when "
                "SPECULATIVE_DS_STANDBY_ENABLED is true"
            )
        if self.trip_stale_sweep_interval_seconds != 30:
            raise ValueError(
                "TRIP_STALE_SWEEP_INTERVAL_SECONDS must be 30 for "
                "Admin Control Plane v0.2"
            )
        if self.projection_heartbeat_interval_seconds != 10.0:
            raise ValueError(
                "PROJECTION_HEARTBEAT_INTERVAL_SECONDS must be 10 for "
                "Admin Control Plane v0.2"
            )
        if (
            self.projection_publisher_enabled
            and not self.projection_rabbitmq_url.strip()
        ):
            raise ValueError(
                "PROJECTION_RABBITMQ_URL is required when the publisher is enabled"
            )
        positive_projection_fields = (
            "projection_publisher_poll_seconds",
            "projection_publisher_retry_seconds",
            "projection_broker_connect_timeout_seconds",
            "projection_publish_confirm_timeout_seconds",
        )
        for field_name in positive_projection_fields:
            if float(getattr(self, field_name)) <= 0:
                raise ValueError(f"{field_name} must be positive")
        positive_fields = (
            "route_estimate_road_factor",
            "commute_daily_budget_factor_driving",
            "commute_daily_budget_factor_transit",
            "commute_daily_budget_factor_walking",
            "commute_daily_budget_factor_cycling",
            "commute_estimate_speed_kmh_driving",
            "commute_estimate_speed_kmh_transit",
            "commute_estimate_speed_kmh_walking",
            "commute_estimate_speed_kmh_cycling",
        )
        for field_name in positive_fields:
            if float(getattr(self, field_name)) <= 0:
                raise ValueError(f"{field_name} must be positive")

        non_negative_fields = (
            "route_single_leg_max",
            "route_single_leg_max_transit",
            "route_single_leg_max_walking",
            "route_single_leg_max_cycling",
            "commute_walk_switch_max_meters",
        )
        for field_name in non_negative_fields:
            if int(getattr(self, field_name)) < 0:
                raise ValueError(f"{field_name} must be non-negative")
        return self

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
