from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """No test may see the real key, the real config file or the network."""
    for name in ("BHIVED_API_KEY", "BHIVED_API_URL", "BHIVED_TIMEOUT", "BHIVED_WARMUP_RETRIES"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("bhived._config.stored_config_path", lambda: tmp_path / ".bhived" / "config.json")
