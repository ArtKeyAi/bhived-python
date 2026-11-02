from __future__ import annotations

import httpx
import pytest

import bhived
from bhived_testkit import QUERY_RESPONSE, WRITE_RESPONSE, FakeAPI, ok


def test_module_functions_share_one_default_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BHIVED_API_KEY", "env-key")
    monkeypatch.setenv("BHIVED_API_URL", "https://env.example")
    api = FakeAPI(ok(QUERY_RESPONSE), ok(WRITE_RESPONSE))
    real_client = httpx.Client

    monkeypatch.setattr(
        "bhived._client.httpx.Client", lambda **kw: real_client(transport=httpx.MockTransport(api), **kw)
    )

    result = bhived.query("httpx respx")
    bhived.write_instruction("Pin httpx<1 for respx 0.21.", "Pin httpx<1 for respx 0.21")

    assert result.query_id == "q-123"
    assert bhived.get_default_client() is bhived.get_default_client()
    assert str(api.requests[0].url) == "https://env.example/v2/query"
    assert api.requests[1].headers["X-API-Key"] == "env-key"
    assert api.body(1)["query_id"] == "q-123"
