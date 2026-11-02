from __future__ import annotations

import logging
from typing import Any

import pytest
from bhived import AuthenticationError
from langchain.agents.middleware import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from langchain_bhived import BhivedMiddleware, BhivedToolkit
from lc_testkit import QUERY_RESPONSE, FakeAPI, ScriptedChatModel, error, make_clients, ok

QUESTION = "Pydantic v2 says class Config is deprecated, how do I fix it?"


def make_middleware(api: FakeAPI, **kwargs: Any) -> BhivedMiddleware:
    clients = make_clients(api)
    return BhivedMiddleware(client=clients.sync, async_client=clients.async_, **kwargs)


def make_request(messages: list[Any], system: str | None = "You are a careful assistant.", tools: list[Any] | None = None) -> ModelRequest:
    return ModelRequest(
        model=ScriptedChatModel(responses=[]),
        messages=messages,
        system_message=SystemMessage(content=system) if system is not None else None,
        tools=tools or [],
        state={"messages": messages},
    )


class Handler:
    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []

    def __call__(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return ModelResponse(result=[AIMessage(content="ok")])

    def system_text(self, index: int = -1) -> str:
        message = self.requests[index].system_message
        assert message is not None
        return "\n".join(block["text"] for block in message.content_blocks if block.get("type") == "text")


def test_lessons_are_appended_to_the_system_message() -> None:
    api = FakeAPI(ok(QUERY_RESPONSE))
    handler = Handler()
    make_middleware(api).wrap_model_call(make_request([HumanMessage(QUESTION)]), handler)

    system = handler.system_text()
    assert system.startswith("You are a careful assistant.")
    assert "## Shared lessons (from bhived)" in system
    assert "Use pydantic v2 model_config, not class Config" in system
    assert "Do NOT call .dict() on pydantic v2 models" in system
    assert "query_id" not in system  # no write tools on this request

    assert api.paths() == ["/v2/query"]
    assert api.body()["query"] == QUESTION
    assert api.body()["top_k"] == 3
    assert api.body()["include_episodes"] is False


def test_query_id_is_shown_when_write_tools_are_available() -> None:
    api = FakeAPI(ok(QUERY_RESPONSE))
    handler = Handler()
    tools = BhivedToolkit(clients=make_clients(api)).get_tools()
    make_middleware(api).wrap_model_call(make_request([HumanMessage(QUESTION)], tools=tools), handler)
    assert "query_id: q-lc-1" in handler.system_text()


def test_works_without_a_system_prompt() -> None:
    api = FakeAPI(ok(QUERY_RESPONSE))
    handler = Handler()
    make_middleware(api).wrap_model_call(make_request([HumanMessage(QUESTION)], system=None), handler)
    assert handler.system_text().startswith("## Shared lessons")


def test_the_original_request_is_not_mutated() -> None:
    api = FakeAPI(ok(QUERY_RESPONSE))
    request = make_request([HumanMessage(QUESTION)])
    make_middleware(api).wrap_model_call(request, Handler())
    assert request.system_message is not None
    assert request.system_message.content == "You are a careful assistant."


def test_latest_human_message_is_used_and_tool_turns_hit_the_cache() -> None:
    api = FakeAPI(ok(QUERY_RESPONSE))
    middleware = make_middleware(api)
    handler = Handler()
    messages: list[Any] = [HumanMessage("An older question about something else entirely"), HumanMessage(QUESTION)]
    middleware.wrap_model_call(make_request(messages), handler)

    # Same user turn, after a tool call: one bhived query in total.
    messages += [
        AIMessage(content="", tool_calls=[{"name": "search", "args": {}, "id": "c1", "type": "tool_call"}]),
        ToolMessage(content="result", tool_call_id="c1"),
    ]
    middleware.wrap_model_call(make_request(messages), handler)

    assert api.paths() == ["/v2/query"]
    assert api.body(0)["query"] == QUESTION
    assert "Shared lessons" in handler.system_text(1)


def test_cache_can_be_disabled() -> None:
    api = FakeAPI(ok(QUERY_RESPONSE), ok(QUERY_RESPONSE))
    middleware = make_middleware(api, cache_size=0)
    request = make_request([HumanMessage(QUESTION)])
    middleware.wrap_model_call(request, Handler())
    middleware.wrap_model_call(request, Handler())
    assert len(api.requests) == 2


def test_short_or_missing_user_messages_skip_recall() -> None:
    api = FakeAPI()
    handler = Handler()
    middleware = make_middleware(api)
    middleware.wrap_model_call(make_request([HumanMessage("thanks")]), handler)
    middleware.wrap_model_call(make_request([AIMessage("hello")]), handler)
    assert api.requests == []
    assert handler.system_text(0) == "You are a careful assistant."


def test_content_blocks_and_long_messages() -> None:
    api = FakeAPI(ok(QUERY_RESPONSE))
    message = HumanMessage(content=[{"type": "text", "text": QUESTION + " " + "x" * 5000}])
    make_middleware(api, max_query_chars=100).wrap_model_call(make_request([message]), Handler())
    assert api.body()["query"] == (QUESTION + " " + "x" * 5000)[:100]


def test_custom_query_builder_and_options() -> None:
    api = FakeAPI(ok(QUERY_RESPONSE))
    middleware = make_middleware(
        api,
        build_query=lambda request: "pydantic ConfigDict deprecation",
        context="Python 3.12, pydantic 2.9",
        top_k=7,
        scope="global_only",
    )
    middleware.wrap_model_call(make_request([HumanMessage(QUESTION)]), Handler())
    assert api.body() == {
        "query": "pydantic ConfigDict deprecation",
        "context": "Python 3.12, pydantic 2.9",
        "top_k": 7,
        "scope": "global_only",
        "include_warnings": True,
        "include_episodes": False,
        "include_disputed": False,
    }


def test_empty_results_add_nothing() -> None:
    api = FakeAPI(ok({"query_id": "q-empty"}))
    handler = Handler()
    make_middleware(api).wrap_model_call(make_request([HumanMessage(QUESTION)]), handler)
    assert handler.system_text() == "You are a careful assistant."


def test_failed_recall_does_not_break_the_model_call(caplog: pytest.LogCaptureFixture) -> None:
    api = FakeAPI(error(403, "Invalid or inactive API key"))
    handler = Handler()
    with caplog.at_level(logging.WARNING, logger="langchain_bhived.middleware"):
        make_middleware(api).wrap_model_call(make_request([HumanMessage(QUESTION)]), handler)
    assert handler.system_text() == "You are a careful assistant."
    assert "bhived recall skipped (AuthenticationError)" in caplog.text
    assert "bhv_test_key" not in caplog.text


def test_missing_key_is_logged_once() -> None:
    api = FakeAPI()
    clients = make_clients(api, api_key=None)
    middleware = BhivedMiddleware(client=clients.sync)
    records: list[logging.LogRecord] = []

    class Collect(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    log = logging.getLogger("langchain_bhived.middleware")
    collector = Collect(level=logging.DEBUG)
    log.addHandler(collector)
    log.setLevel(logging.DEBUG)
    try:
        for _ in range(3):
            middleware.wrap_model_call(make_request([HumanMessage(QUESTION)]), Handler())
    finally:
        log.removeHandler(collector)
        log.setLevel(logging.NOTSET)
    assert [r.levelno for r in records] == [logging.WARNING, logging.DEBUG, logging.DEBUG]
    assert api.requests == []


def test_raise_on_error() -> None:
    api = FakeAPI(error(403, "Invalid or inactive API key"))
    with pytest.raises(AuthenticationError):
        make_middleware(api, raise_on_error=True).wrap_model_call(make_request([HumanMessage(QUESTION)]), Handler())


@pytest.mark.parametrize(
    "kwargs",
    [{"top_k": 0}, {"top_k": 101}, {"scope": "everyone"}, {"max_tokens": 50}],
)
def test_invalid_options(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        BhivedMiddleware(**kwargs)


@pytest.mark.asyncio
async def test_async_hook() -> None:
    api = FakeAPI(ok(QUERY_RESPONSE))
    seen: list[ModelRequest] = []

    async def handler(request: ModelRequest) -> ModelResponse:
        seen.append(request)
        return ModelResponse(result=[AIMessage(content="ok")])

    await make_middleware(api).awrap_model_call(make_request([HumanMessage(QUESTION)]), handler)
    assert seen[0].system_message is not None
    assert "Shared lessons" in str(seen[0].system_message.content)
    assert api.paths() == ["/v2/query"]
