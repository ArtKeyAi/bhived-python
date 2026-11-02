from __future__ import annotations

import httpx
import pytest

from bhived import WriteOutcomeUnknownError
from bhived_testkit import QUERY_RESPONSE, WRITE_RESPONSE, error, make_async_client, ok


@pytest.mark.asyncio
async def test_async_query_and_linked_write() -> None:
    client, api, _ = make_async_client(ok(QUERY_RESPONSE), ok(WRITE_RESPONSE))
    result = await client.query("respx httpx", top_k=3)
    assert result.query_id == "q-123"

    written = await client.write_mistake("Patching send hides timeouts.", "Do not patch httpx send")
    assert api.body()["query_id"] == "q-123"
    assert api.body()["type"] == "mistake"
    assert written.bhived_id == "new-1"
    await client.aclose()


@pytest.mark.asyncio
async def test_async_warming_retry() -> None:
    warming = error(503, {"detail": "models_warming"})
    client, _, sleeps = make_async_client(warming, ok(QUERY_RESPONSE))
    await client.query("x")
    assert sleeps == [1.0]


@pytest.mark.asyncio
async def test_async_unknown_outcome_keeps_key() -> None:
    client, api, _ = make_async_client(httpx.ConnectError, httpx.ConnectError, ok(WRITE_RESPONSE))
    with pytest.raises(WriteOutcomeUnknownError):
        await client.write_update("httpx 0.28 removed proxies=", "httpx 0.28 renamed proxies to proxy")
    await client.write_update("httpx 0.28 removed proxies=", "httpx 0.28 renamed proxies to proxy")
    assert api.header("Idempotency-Key", 0) == api.header("Idempotency-Key", 2)
