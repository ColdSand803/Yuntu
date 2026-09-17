import os
from src.config import Settings
from src.agents.llm import resolve_role_config

def test_gemini_custom_base_url():
    s = Settings(
        _env_file=None,
        gemini_api_key="sk-newapi-custom",
        gemini_base_url="https://api.newapi-relay.com/v1",
        intent_provider="gemini",
        intent_model="gemini-2.5-flash",
        intent_api_key="",
    )
    from unittest.mock import patch
    with patch("src.agents.llm.get_settings", return_value=s):
        cfg = resolve_role_config("intent")
        assert cfg.provider == "gemini"
        assert cfg.api_key == "sk-newapi-custom"
        assert cfg.base_url == "https://api.newapi-relay.com/v1"
        assert cfg.model == "gemini-2.5-flash"

def test_gemini_default_fallback():
    s = Settings(
        _env_file=None,
        gemini_api_key="official-key",
        gemini_base_url="",
        intent_provider="gemini",
        intent_model="gemini-2.5-flash",
        intent_api_key="",
    )
    from unittest.mock import patch
    with patch("src.agents.llm.get_settings", return_value=s):
        cfg = resolve_role_config("intent")
        assert cfg.provider == "gemini"
        assert cfg.api_key == "official-key"
        assert cfg.base_url == "https://generativelanguage.googleapis.com/v1beta/openai/"

def test_openai_provider():
    s = Settings(
        _env_file=None,
        openai_api_key="sk-custom-openai",
        openai_base_url="https://custom.relay.com/v1",
        intent_provider="openai",
        intent_model="gpt-4o",
        intent_api_key="",
    )
    from unittest.mock import patch
    with patch("src.agents.llm.get_settings", return_value=s):
        cfg = resolve_role_config("intent")
        assert cfg.provider == "openai"
        assert cfg.api_key == "sk-custom-openai"
        assert cfg.base_url == "https://custom.relay.com/v1"

def test_all_roles_with_gemini_relay():
    s = Settings(
        _env_file=None,
        gemini_api_key="sk-relay-key",
        gemini_base_url="https://relay.test.com/v1",
        intent_provider="gemini",
        intent_model="gemini-2.5-flash",
        intent_api_key="",
        writer_provider="gemini",
        writer_model="gemini-2.5-pro",
        writer_api_key="",
        review_provider="gemini",
        review_model="gemini-2.5-flash",
        review_api_key="",
        grouping_provider="gemini",
        grouping_model="gemini-2.5-flash",
        grouping_api_key="",
        selector_provider="gemini",
        selector_model="gemini-2.5-flash",
        selector_api_key="",
        extract_provider="gemini",
        extract_model="gemini-2.5-flash",
        extract_api_key="",
    )
    from unittest.mock import patch
    with patch("src.agents.llm.get_settings", return_value=s):
        for role in ["intent", "writer", "review", "grouping", "selector", "extract"]:
            cfg = resolve_role_config(role)
            assert cfg.base_url == "https://relay.test.com/v1"
            assert cfg.api_key == "sk-relay-key"
