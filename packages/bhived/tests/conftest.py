from __future__ import annotations

from typing import Any

import pytest

import bhived


@pytest.fixture(autouse=True)
def isolated_env(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, tmp_path) -> Any:
    """No test may see the real key, the real config file or the network.

    The one exception is the opt-in live smoke test (marked ``live``).
    """
    if request.node.get_closest_marker("live"):
        return None
    for name in ("BHIVED_API_KEY", "BHIVED_API_URL", "BHIVED_TIMEOUT", "BHIVED_WARMUP_RETRIES"):
        monkeypatch.delenv(name, raising=False)
    config_file = tmp_path / ".bhived" / "config.json"
    monkeypatch.setattr("bhived._config.stored_config_path", lambda: config_file)
    monkeypatch.setattr(bhived, "_default_client", None)
    return config_file
