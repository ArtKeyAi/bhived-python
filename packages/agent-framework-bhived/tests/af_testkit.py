"""Offline test helpers for agent-framework-bhived: a scripted bhived API and chat client."""

from __future__ import annotations

import json
from typing import Any, Optional

import httpx
from agent_framework import BaseChatClient, ChatResponse, Content, FunctionInvocationLayer, Message
from bhived import AsyncBhivedClient, BhivedClient, BhivedConfig

from agent_framework_bhived import BhivedClients

TEST_KEY = "bhv_test_key_do_not_print_af0"
TEST_URL = "https://api.bhived.test"

QUERY_RESPONSE: dict[str, Any] = {
    "query_id": "q-af-1",
    "public_recommendations": [
        {
            "id": "m-1",
            "title": "azure-identity: use DefaultAzureCredential locally and in CI",
            "text": "azure-identity 1.19: DefaultAzureCredential tries env vars, then managed identity, "
            "then the Azure CLI. Set AZURE_CLIENT_ID in CI instead of hardcoding a secret.",
            "type": "instruction",
            "status": "active",
            "score": 0.79,
        }
    ],
    "public_warnings": [
        {
            "id": "w-1",
            "title": "Do NOT commit a client secret to make CI pass",
            "text": "Use a federated credential or a pipeline secret, never a literal in code.",
            "confidence": 0.72,
        }
    ],
}

WRITE_RESPONSE: dict[str, Any] = {
    "memory_id": "lesson-af-1",
    "entities_created": 2,
    "entities_merged": 0,
    "relations_created": 1,
    "query_id_linked": "q-af-1",
    "supersedes_id_linked": None,
    "action_performed": "created",
}


class FakeAPI:
    """A scripted server. Each item is a response or an exception class."""

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
        return item

    def paths(self) -> list[str]:
        return [request.url.path for request in self.requests]

    def body(self, index: int = -1) -> dict[str, Any]:
        return json.loads(self.requests[index].content)


def text_of(output: Any) -> str:
    """The text of a FunctionTool.invoke() result (a list of Content)."""
    if isinstance(output, list):
        return "\n".join(str(getattr(item, "text", None) or "") for item in output)
    return str(output)


def ok(data: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json=data)


def error(status: int, detail: Any) -> httpx.Response:
    return httpx.Response(status, json={"detail": detail})


def make_clients(api: FakeAPI, api_key: Optional[str] = TEST_KEY) -> BhivedClients:
    config = BhivedConfig(api_key=api_key, api_url=TEST_URL, timeout=5.0)
    transport = httpx.MockTransport(api)
    sync = BhivedClient(config=config, http_client=httpx.Client(transport=transport))
    async_ = AsyncBhivedClient(config=config, http_client=httpx.AsyncClient(transport=transport))

    async def no_sleep(seconds: float) -> None:
        return None

    sync._sleep = lambda seconds: None
    async_._sleep = no_sleep
    return BhivedClients(client=sync, async_client=async_)


class ScriptedChatClient(FunctionInvocationLayer, BaseChatClient):
    """Plays back scripted turns and records what each call received.

    A turn is a string (a text answer) or ``{"tool": name, "arguments": {...}}``
    (a function call, which the function-invocation layer then runs).
    """

    def __init__(self, turns: list[Any]) -> None:
        super().__init__()
        self.turns = list(turns)
        self.calls: list[dict[str, Any]] = []

    def _inner_get_response(self, *, messages: Any, stream: bool, options: Any, **kwargs: Any) -> Any:
        self.calls.append({"messages": list(messages), "options": dict(options)})
        turn = self.turns.pop(0)

        async def respond() -> ChatResponse:
            if isinstance(turn, dict):
                content = Content.from_function_call(
                    call_id=f"call-{len(self.calls)}", name=turn["tool"], arguments=turn["arguments"]
                )
                return ChatResponse(messages=[Message("assistant", [content])])
            return ChatResponse(messages=[Message("assistant", [turn])])

        return respond()

    def instructions(self, call: int) -> str:
        return str(self.calls[call]["options"].get("instructions") or "")
