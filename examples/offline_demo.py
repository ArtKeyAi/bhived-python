"""Run the example agent with no network and no API keys.

A scripted chat model stands in for the LLM, and a fake bhived API answers
over httpx.MockTransport. The script prints what the middleware added to the
system prompt, which tool the model called, and what the fake API received.

    python examples/offline_demo.py
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from bhived import AsyncBhivedClient, BhivedClient, BhivedConfig
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from langchain_agent import build_agent
from langchain_bhived import BhivedClients

QUESTION = "pydantic 2 says class Config is deprecated. What should I use?"

FAKE_QUERY_RESULT = {
    "query_id": "demo-query-1",
    "public_recommendations": [
        {
            "id": "demo-lesson-1",
            "title": "pydantic 2: use model_config = ConfigDict(...)",
            "text": "In pydantic 2.x the inner `class Config` is deprecated. Move its options to "
            "`model_config = ConfigDict(...)`; `orm_mode` became `from_attributes`.",
            "type": "instruction",
            "status": "active",
            "score": 0.84,
        }
    ],
    "public_warnings": [
        {
            "id": "demo-warning-1",
            "title": "Do NOT keep calling .dict() after moving to pydantic 2",
            "text": "`.dict()` still works but warns and will be removed. Use `.model_dump()`.",
            "confidence": 0.7,
        }
    ],
}


class FakeBhivedAPI:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.calls.append((request.url.path, body))
        if request.url.path == "/v2/query":
            return httpx.Response(200, json=FAKE_QUERY_RESULT)
        return httpx.Response(404, json={"detail": "not in this demo"})


class ScriptedModel(BaseChatModel):
    """Looks up the lesson once, then answers using it."""

    seen: list[list[BaseMessage]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted-demo"

    def _generate(self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        self.seen.append(list(messages))
        if not any(isinstance(m, ToolMessage) for m in messages):
            call = {
                "name": "bhived_query",
                "args": {"query": "pydantic 2 orm_mode from_attributes", "context": "pydantic 2.9"},
                "id": "call_demo_1",
                "type": "tool_call",
            }
            message = AIMessage(content="", tool_calls=[call])
        else:
            message = AIMessage(
                content="Replace the inner `class Config` with `model_config = ConfigDict(...)` "
                "(and rename `orm_mode` to `from_attributes`). This follows the shared lesson "
                "'pydantic 2: use model_config = ConfigDict(...)'."
            )
        return ChatResult(generations=[ChatGeneration(message=message)])

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedModel":
        return self


def fake_clients(api: FakeBhivedAPI) -> BhivedClients:
    config = BhivedConfig(api_key="demo-key", api_url="https://bhived.invalid")
    transport = httpx.MockTransport(api)
    return BhivedClients(
        client=BhivedClient(config=config, http_client=httpx.Client(transport=transport)),
        async_client=AsyncBhivedClient(config=config, http_client=httpx.AsyncClient(transport=transport)),
    )


def main() -> dict[str, Any]:
    api = FakeBhivedAPI()
    model = ScriptedModel()
    agent = build_agent(model, clients=fake_clients(api))
    result = agent.invoke({"messages": [{"role": "user", "content": QUESTION}]})

    print("System prompt the model saw on its first call:\n")
    print(model.seen[0][0].content if isinstance(model.seen[0][0].content, str) else _text(model.seen[0][0].content))
    print("\nRequests the fake bhived API received:")
    for path, body in api.calls:
        print(f"  POST {path}  query={body.get('query')!r}")
    print("\nAgent answer:\n")
    print(result["messages"][-1].content)
    return {"api_calls": api.calls, "seen": model.seen, "result": result}


def _text(content: Any) -> str:
    return "\n\n".join(block.get("text", "") for block in content if isinstance(block, dict))


if __name__ == "__main__":
    main()
