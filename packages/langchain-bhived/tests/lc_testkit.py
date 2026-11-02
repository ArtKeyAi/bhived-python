"""Offline test helpers for langchain-bhived: a scripted bhived API and chat model."""

from __future__ import annotations

import json
from typing import Any, Optional

import httpx
from bhived import AsyncBhivedClient, BhivedClient, BhivedConfig
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from langchain_bhived import BhivedClients

TEST_KEY = "bhv_test_key_do_not_print_456"
TEST_URL = "https://api.bhived.test"

QUERY_RESPONSE: dict[str, Any] = {
    "query_id": "q-lc-1",
    "team_recommendations": [],
    "public_recommendations": [
        {
            "id": "m-1",
            "title": "Use pydantic v2 model_config, not class Config",
            "text": "In pydantic 2.x, `class Config` is deprecated. Use `model_config = ConfigDict(...)`.",
            "type": "instruction",
            "status": "active",
            "score": 0.8,
        }
    ],
    "public_warnings": [
        {
            "id": "w-1",
            "title": "Do NOT call .dict() on pydantic v2 models",
            "text": "`.dict()` is deprecated in pydantic 2; use `.model_dump()`.",
            "confidence": 0.7,
        }
    ],
}

WRITE_RESPONSE: dict[str, Any] = {
    "memory_id": "lesson-1",
    "entities_created": 2,
    "entities_merged": 0,
    "relations_created": 1,
    "causal_relations": 0,
    "query_id_linked": "q-lc-1",
    "supersedes_id_linked": None,
    "action_performed": "created",
    "corroborations_created": 1,
    "contradictions_created": 0,
}


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

    def paths(self) -> list[str]:
        return [request.url.path for request in self.requests]

    def body(self, index: int = -1) -> dict[str, Any]:
        return json.loads(self.requests[index].content)


def ok(data: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json=data)


def error(status: int, detail: Any) -> httpx.Response:
    return httpx.Response(status, json={"detail": detail})


def make_clients(api: FakeAPI, api_key: Optional[str] = TEST_KEY) -> BhivedClients:
    """Sync and async clients that both talk to the same fake API."""
    config = BhivedConfig(api_key=api_key, api_url=TEST_URL, timeout=5.0)
    sync = BhivedClient(config=config, http_client=httpx.Client(transport=httpx.MockTransport(api)))
    async_ = AsyncBhivedClient(config=config, http_client=httpx.AsyncClient(transport=httpx.MockTransport(api)))

    async def no_sleep(seconds: float) -> None:
        return None

    sync._sleep = lambda seconds: None
    async_._sleep = no_sleep
    return BhivedClients(client=sync, async_client=async_)


class ScriptedChatModel(BaseChatModel):
    """Returns the scripted messages in order and records what it was sent."""

    responses: list[AIMessage]
    seen: list[list[BaseMessage]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        self.seen.append(list(messages))
        message = self.responses[len(self.seen) - 1]
        return ChatResult(generations=[ChatGeneration(message=message)])

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedChatModel":
        return self
