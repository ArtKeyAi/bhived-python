from __future__ import annotations

import json

import pytest

from bhived import DEFAULT_API_URL, BhivedClient, BhivedConfig
from bhived_testkit import TEST_KEY


def write_stored(path, **data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_defaults_without_any_source() -> None:
    config = BhivedConfig.resolve()
    assert config.api_key is None
    assert config.api_url == DEFAULT_API_URL
    assert config.timeout == 30.0
    assert config.warmup_retries == 5


def test_stored_config_is_used(isolated_env) -> None:
    write_stored(isolated_env, apiKey="stored-key", apiUrl="https://stored.example/")
    config = BhivedConfig.resolve()
    assert config.api_key == "stored-key"
    assert config.api_url == "https://stored.example"


def test_env_beats_stored_and_argument_beats_env(isolated_env, monkeypatch: pytest.MonkeyPatch) -> None:
    write_stored(isolated_env, apiKey="stored-key", apiUrl="https://stored.example")
    monkeypatch.setenv("BHIVED_API_KEY", "env-key")
    monkeypatch.setenv("BHIVED_API_URL", "https://env.example")
    assert BhivedConfig.resolve().api_key == "env-key"
    assert BhivedConfig.resolve().api_url == "https://env.example"
    assert BhivedConfig.resolve(api_key="arg-key").api_key == "arg-key"


def test_env_key_still_uses_stored_url(isolated_env, monkeypatch: pytest.MonkeyPatch) -> None:
    # Same as bhived-mcp: the stored URL applies even when the key comes from the environment.
    write_stored(isolated_env, apiKey="stored-key", apiUrl="https://stored.example")
    monkeypatch.setenv("BHIVED_API_KEY", "env-key")
    assert BhivedConfig.resolve().api_url == "https://stored.example"


def test_blank_env_key_falls_through(isolated_env, monkeypatch: pytest.MonkeyPatch) -> None:
    write_stored(isolated_env, apiKey="stored-key")
    monkeypatch.setenv("BHIVED_API_KEY", "   ")
    assert BhivedConfig.resolve().api_key == "stored-key"


def test_keyless_or_broken_stored_file_is_ignored(isolated_env) -> None:
    write_stored(isolated_env, apiUrl="https://stored.example")
    assert BhivedConfig.resolve().api_url == DEFAULT_API_URL
    isolated_env.write_text("{not json", encoding="utf-8")
    assert BhivedConfig.resolve().api_key is None


def test_timeout_env_is_milliseconds_and_bad_values_fall_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BHIVED_TIMEOUT", "12000")
    monkeypatch.setenv("BHIVED_WARMUP_RETRIES", "2")
    config = BhivedConfig.resolve()
    assert config.timeout == 12.0
    assert config.warmup_retries == 2
    monkeypatch.setenv("BHIVED_TIMEOUT", "soon")
    monkeypatch.setenv("BHIVED_WARMUP_RETRIES", "many")
    config = BhivedConfig.resolve()
    assert config.timeout == 30.0
    assert config.warmup_retries == 5


def test_repr_never_shows_the_key() -> None:
    config = BhivedConfig(api_key=TEST_KEY)
    client = BhivedClient(config=config)
    assert TEST_KEY not in repr(config)
    assert TEST_KEY not in repr(client)
    assert "***" in repr(client)
    client.close()
