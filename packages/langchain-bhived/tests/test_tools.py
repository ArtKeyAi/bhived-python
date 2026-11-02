from __future__ import annotations

import httpx
import pytest

from langchain_bhived import BhivedQueryTool, BhivedToolkit, BhivedWriteInstructionTool
from lc_testkit import QUERY_RESPONSE, TEST_KEY, WRITE_RESPONSE, FakeAPI, error, make_clients, ok

LESSON = {
    "text": "**Context:** pydantic 2.9\n**Solution:** use model_config = ConfigDict(...)\n**Verified:** tests pass",
    "title": "pydantic 2: replace class Config with model_config",
}


def tools_by_name(api: FakeAPI, **kwargs) -> dict:
    return {tool.name: tool for tool in BhivedToolkit(clients=make_clients(api), **kwargs).get_tools()}


def test_toolkit_names_and_read_only() -> None:
    api = FakeAPI()
    assert list(tools_by_name(api)) == [
        "bhived_query",
        "bhived_write_instruction",
        "bhived_write_mistake",
        "bhived_write_update",
    ]
    assert list(tools_by_name(api, read_only=True)) == ["bhived_query"]


def test_write_descriptions_carry_the_privacy_rules() -> None:
    for name, tool in tools_by_name(FakeAPI()).items():
        if name == "bhived_query":
            assert "query_id" in tool.description
            continue
        for phrase in ("secrets", "credentials", "customer", "proprietary code", "PUBLIC shared lessons", "team"):
            assert phrase in tool.description, (name, phrase)


def test_tool_schemas() -> None:
    tools = tools_by_name(FakeAPI())
    query_args = tools["bhived_query"].args
    assert set(query_args) == {"query", "context", "top_k", "scope"}
    write_args = tools["bhived_write_mistake"].args
    assert set(write_args) == {"text", "title", "query_id", "model", "supersedes_id", "action"}
    assert write_args["title"]["maxLength"] == 100


def test_query_tool_returns_markdown_with_query_id() -> None:
    api = FakeAPI(ok(QUERY_RESPONSE))
    output = tools_by_name(api)["bhived_query"].invoke({"query": "pydantic class Config deprecated", "top_k": 2})
    assert "Use pydantic v2 model_config" in output
    assert "query_id: `q-lc-1`" in output
    assert api.body()["top_k"] == 2


def test_write_tool_sends_only_the_query_id_it_was_given() -> None:
    api = FakeAPI(ok(QUERY_RESPONSE), ok(WRITE_RESPONSE), ok(WRITE_RESPONSE))
    tools = tools_by_name(api)
    tools["bhived_query"].invoke({"query": "pydantic class Config deprecated"})

    output = tools["bhived_write_instruction"].invoke({**LESSON, "query_id": "q-lc-1", "model": "claude-sonnet-5-5"})
    assert "Lesson created." in output
    assert api.body()["query_id"] == "q-lc-1"
    assert api.body()["type"] == "instruction"
    assert api.requests[-1].headers["Idempotency-Key"]

    # Without an explicit query_id the tool must not borrow the client's last query.
    tools["bhived_write_mistake"].invoke(LESSON)
    assert "query_id" not in api.body()


def test_duplicate_comes_back_to_the_model_as_text() -> None:
    duplicate = error(409, {"error": "duplicate_memory", "duplicate_of": "m-old", "jaccard_similarity": 0.88})
    api = FakeAPI(duplicate)
    output = tools_by_name(api)["bhived_write_update"].invoke(LESSON)
    assert "NOT saved" in output
    assert "m-old" in output and "88%" in output


def test_unknown_outcome_tells_the_model_to_retry_identically() -> None:
    api = FakeAPI(httpx.ConnectError, httpx.ConnectError, ok(WRITE_RESPONSE))
    tool = tools_by_name(api)["bhived_write_instruction"]
    output = tool.invoke(LESSON)
    assert "outcome unknown" in output
    tool.invoke(LESSON)
    assert api.requests[0].headers["Idempotency-Key"] == api.requests[2].headers["Idempotency-Key"]


def test_query_error_is_returned_not_raised_and_never_shows_the_key() -> None:
    api = FakeAPI(error(403, "Invalid or inactive API key"))
    output = tools_by_name(api)["bhived_query"].invoke({"query": "anything at all"})
    assert output.startswith("Error querying bhived")
    assert TEST_KEY not in output


def test_tools_build_their_own_clients_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BHIVED_API_KEY", TEST_KEY)
    tool = BhivedWriteInstructionTool()
    assert tool.clients.config.api_key == TEST_KEY
    assert TEST_KEY not in repr(tool)
    assert TEST_KEY not in repr(BhivedToolkit())
    assert BhivedQueryTool().clients.config.api_url == "https://mcp.bhived.ai"


@pytest.mark.asyncio
async def test_async_tools() -> None:
    api = FakeAPI(ok(QUERY_RESPONSE), ok(WRITE_RESPONSE))
    tools = tools_by_name(api)
    output = await tools["bhived_query"].ainvoke({"query": "pydantic class Config deprecated"})
    assert "q-lc-1" in output
    output = await tools["bhived_write_instruction"].ainvoke({**LESSON, "query_id": "q-lc-1"})
    assert "Lesson created." in output
    assert api.body()["query_id"] == "q-lc-1"
