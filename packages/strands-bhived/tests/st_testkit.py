"""Offline test helpers for strands-bhived: a scripted bhived API and a scripted Strands model."""

from __future__ import annotations

import copy
import json
from typing import Any, AsyncIterator, Optional

import httpx
from bhived import AsyncBhivedClient, BhivedClient, BhivedConfig
from strands.models import Model

from strands_bhived import BhivedClients

TEST_KEY = "bhv_test_key_do_not_print_789"
TEST_URL = "https://api.bhived.test"

QUERY_RESPONSE: dict[str, Any] = {
    "query_id": "q-st-1",
    "public_recommendations": [
        {
            "id": "m-1",
            "title": "boto3: pass region_name explicitly in Lambda",
            "text": "boto3 1.35 raises NoRegionError outside AWS_DEFAULT_REGION. Pass region_name to the client.",
            "type": "instruction",
            "status": "active",
            "score": 0.81,
        }
    ],
    "public_warnings": [
        {
            "id": "w-1",
            "title": "Do NOT create a boto3 client per request",
            "text": "Creating clients per request adds ~100 ms and leaks connections. Reuse one client.",
            "confidence": 0.7,
        }
    ],
}

WRITE_RESPONSE: dict[str, Any] = {
    "memory_id": "lesson-st-1",
    "entities_created": 2,
    "entities_merged": 0,
    "relations_created": 1,
    "query_id_linked": "q-st-1",
    "supersedes_id_linked": None,
    "action_performed": "created",
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
    config = BhivedConfig(api_key=api_key, api_url=TEST_URL, timeout=5.0)
    transport = httpx.MockTransport(api)
    sync = BhivedClient(config=config, http_client=httpx.Client(transport=transport))
    async_ = AsyncBhivedClient(config=config, http_client=httpx.AsyncClient(transport=transport))

    async def no_sleep(seconds: float) -> None:
        return None

    sync._sleep = lambda seconds: None
    async_._sleep = no_sleep
    return BhivedClients(client=sync, async_client=async_)


class ScriptedModel(Model):
    """Plays back scripted turns and records what each model call received.

    A turn is either a string (a text answer) or a dict
    ``{"tool": name, "input": {...}}`` (a tool call).
    """

    def __init__(self, turns: list[Any]) -> None:
        self.turns = list(turns)
        self.calls: list[dict[str, Any]] = []

    def update_config(self, **model_config: Any) -> None:
        return None

    def get_config(self) -> dict[str, Any]:
        return {}

    async def structured_output(self, output_model: Any, prompt: Any, system_prompt: Any = None, **kwargs: Any):  # type: ignore[override]
        raise NotImplementedError
        yield  # pragma: no cover

    async def stream(  # type: ignore[override]
        self, messages: Any, tool_specs: Any = None, system_prompt: Any = None, **kwargs: Any
    ) -> AsyncIterator[dict[str, Any]]:
        self.calls.append(
            {
                "messages": copy.deepcopy(messages),
                "system_prompt": system_prompt,
                "tools": [spec["name"] for spec in tool_specs or []],
            }
        )
        turn = self.turns.pop(0)
        yield {"messageStart": {"role": "assistant"}}
        if isinstance(turn, dict):
            call_id = f"call-{len(self.calls)}"
            yield {"contentBlockStart": {"start": {"toolUse": {"toolUseId": call_id, "name": turn["tool"]}}}}
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(turn["input"])}}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        else:
            yield {"contentBlockStart": {"start": {}}}
            yield {"contentBlockDelta": {"delta": {"text": turn}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}

    def text_seen(self, call: int) -> str:
        """All text the model received on one call, across messages and content blocks."""
        parts: list[str] = []
        for message in self.calls[call]["messages"]:
            for block in message.get("content", []):
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    parts.append(block["text"])
        return "\n".join(parts)
