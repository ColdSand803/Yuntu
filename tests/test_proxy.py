"""Unit tests for database and LLM proxy configuration and socket tunneling."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from src.config import Settings
from src.pipeline.db_proxy import (
    check_and_install_db_proxy,
    install_asyncpg_proxy_hook,
    parse_proxy_url,
)


class ProxyUrlParserTests(unittest.TestCase):
    def test_empty_proxy_returns_empty(self) -> None:
        self.assertEqual(parse_proxy_url(""), {})
        self.assertEqual(parse_proxy_url("   "), {})

    def test_http_proxy_defaults(self) -> None:
        res = parse_proxy_url("http://127.0.0.1:7890")
        self.assertEqual(res["scheme"], "http")
        self.assertEqual(res["host"], "127.0.0.1")
        self.assertEqual(res["port"], 7890)
        self.assertIsNone(res["username"])
        self.assertIsNone(res["password"])

    def test_socks5_with_auth(self) -> None:
        res = parse_proxy_url("socks5://admin:secret123@proxy.lan:1080")
        self.assertEqual(res["scheme"], "socks5")
        self.assertEqual(res["host"], "proxy.lan")
        self.assertEqual(res["port"], 1080)
        self.assertEqual(res["username"], "admin")
        self.assertEqual(res["password"], "secret123")

    def test_no_scheme_defaults_to_http(self) -> None:
        res = parse_proxy_url("127.0.0.1:7890")
        self.assertEqual(res["scheme"], "http")
        self.assertEqual(res["host"], "127.0.0.1")
        self.assertEqual(res["port"], 7890)

    def test_unsupported_scheme_raises(self) -> None:
        with self.assertRaises(ValueError):
            parse_proxy_url("ftp://127.0.0.1:21")


class AsyncpgProxyHookTests(unittest.TestCase):
    def test_install_hook_idempotent(self) -> None:
        import asyncpg.connect_utils as cu
        install_asyncpg_proxy_hook("http://127.0.0.1:7890")
        self.assertTrue(getattr(cu, "_yuntu_proxy_installed", False))
        # Re-install should be a no-op
        install_asyncpg_proxy_hook("http://127.0.0.1:7890")
        self.assertTrue(getattr(cu, "_yuntu_proxy_installed", False))

    def test_check_and_install_db_proxy_when_empty(self) -> None:
        s = Settings(_env_file=None, database_proxy="")
        with patch("src.config.get_settings", return_value=s):
            # Should not fail
            check_and_install_db_proxy()


class LlmProxyConfigTests(unittest.TestCase):
    def test_settings_includes_proxy_fields(self) -> None:
        s = Settings(
            _env_file=None,
            database_proxy="http://127.0.0.1:7890",
            llm_proxy="socks5://127.0.0.1:1080",
        )
        self.assertEqual(s.database_proxy, "http://127.0.0.1:7890")
        self.assertEqual(s.llm_proxy, "socks5://127.0.0.1:1080")

    def test_get_client_instantiates_with_proxy(self) -> None:
        from src.agents.llm import _get_client
        s = Settings(
            _env_file=None,
            llm_proxy="http://127.0.0.1:7890",
            openai_api_key="sk-test",
            openai_base_url="https://api.test.com/v1",
        )
        with patch("src.agents.llm.get_settings", return_value=s):
            client = _get_client("openai", "sk-test", "https://api.test.com/v1")
            self.assertIsNotNone(client)
            # Transport is configured
            self.assertIsNotNone(client._client._transport)


if __name__ == "__main__":
    unittest.main()