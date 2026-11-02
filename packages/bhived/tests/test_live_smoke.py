"""Opt-in smoke test against the real API. It only reads; it never writes.

Runs only when BHIVED_LIVE_SMOKE=1 and a key is already configured
(BHIVED_API_KEY or ~/.bhived/config.json).
"""

from __future__ import annotations

import os

import pytest

import bhived

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("BHIVED_LIVE_SMOKE") != "1", reason="set BHIVED_LIVE_SMOKE=1 to run"),
]


def test_live_query_only() -> None:
    config = bhived.BhivedConfig.resolve()
    if not config.api_key:
        pytest.skip("no bhived key configured")
    with bhived.BhivedClient(config=config) as client:
        result = client.query("httpx ReadTimeout retry", context="python httpx", top_k=2)
    assert result.query_id
    assert isinstance(result.to_markdown(), str)
