"""Offline test helpers: a scripted fake API behind httpx.MockTransport."""

from __future__ import annotations

import json
from typing import Any

import httpx

from bhived import AsyncBhivedClient, BhivedClient, BhivedConfig

TEST_KEY = "bhv_test_key_do_not_print_123"
TEST_URL = "https://api.bhived.test"


class FakeAPI:
    """A scripted server. Each item is a response, an exception class, or a callable."""

    def __init__(self, *items: Any) -> None:
        self.items = list(items)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self.items:
            raise AssertionError(f"unexpected request: {request.method} {request.url}")
        item = self.items.pop(0)
        if isinstance(item, type) and issubclass(item, Exception):
            raise item("scripted failure", request=request)
        if callable(item) and not isinstance(item, httpx.Response):
            return item(request)
        return item

    def body(self, index: int = -1) -> dict[str, Any]:
        return json.loads(self.requests[index].content)

    def header(self, name: str, index: int = -1) -> str | None:
        return self.requests[index].headers.get(name)


def ok(data: dict[str, Any], status: int = 200, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, json=data, headers=headers)


def error(status: int, detail: Any, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, json={"detail": detail}, headers=headers)


QUERY_RESPONSE: dict[str, Any] = {
    "query_id": "q-123",
    "team_recommendations": [],
    "public_recommendations": [
        {
            "id": "m-1",
            "title": "Pin httpx below 1.0 with respx 0.21",
            "text": "respx 0.21 breaks with httpx 1.0 betas. Pin httpx<1 until respx ships support.",
            "type": "instruction",
            "status": "active",
            "score": 0.83,
            "corroboration_count": 2,
        },
        {
            "memory_id": "m-2",
            "title": "Use httpx.MockTransport for offline tests",
            "text": "httpx ships MockTransport; no extra mocking library is needed.",
            "type": "instruction",
            "status": "active",
            "score": 0.61,
        },
        {
            "id": "m-skill",
            "title": "pytest helper skill",
            "text": "A skill bundle",
            "type": "note",
            "status": "active",
            "score": 0.5,
            "has_skill": True,
            "skill_meta": {"name": "pytest-helper", "description": "Runs and triages pytest suites."},
        },
    ],
    "team_warnings": [],
    "public_warnings": [
        {
            "id": "w-1",
            "title": "Do NOT patch httpx.Client.send",
            "text": "Patching send skips transport hooks and hides timeout bugs.",
            "type": "mistake",
            "confidence": 0.72,
        }
    ],
    "public_disputed": [
        {"memory_a_id": "m-1", "memory_a_text": "Pin httpx", "memory_b_id": "m-9", "memory_b_text": "Do not pin", "confidence": 0.4}
    ],
    "public_failed_approaches": [{"id": "f-1", "title": "Monkeypatching sockets", "reason": "Flaky on Windows."}],
    "public_episodes": [],
}

WRITE_RESPONSE: dict[str, Any] = {
    "memory_id": "new-1",
    "entities_created": 3,
    "entities_merged": 1,
    "relations_created": 2,
    "causal_relations": 0,
    "next_edge_created": False,
    "provenance_steps": 1,
    "fingerprint_computed": True,
    "query_id_linked": "q-123",
    "supersedes_id_linked": None,
    "action_performed": "created",
    "corroborations_created": 1,
    "contradictions_created": 0,
}


class Sleeps(list):
    def __call__(self, seconds: float) -> None:
        self.append(seconds)


class AsyncSleeps(list):
    async def __call__(self, seconds: float) -> None:
        self.append(seconds)


def make_client(*items: Any, warmup_retries: int = 5) -> tuple[BhivedClient, FakeAPI, Sleeps]:
    api = FakeAPI(*items)
    client = BhivedClient(
        config=BhivedConfig(api_key=TEST_KEY, api_url=TEST_URL, timeout=5.0, warmup_retries=warmup_retries),
        http_client=httpx.Client(transport=httpx.MockTransport(api)),
    )
    sleeps = Sleeps()
    client._sleep = sleeps
    return client, api, sleeps


def make_async_client(*items: Any) -> tuple[AsyncBhivedClient, FakeAPI, AsyncSleeps]:
    api = FakeAPI(*items)
    client = AsyncBhivedClient(
        config=BhivedConfig(api_key=TEST_KEY, api_url=TEST_URL, timeout=5.0),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(api)),
    )
    sleeps = AsyncSleeps()
    client._sleep = sleeps
    return client, api, sleeps
