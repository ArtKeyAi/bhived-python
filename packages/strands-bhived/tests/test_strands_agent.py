"""End to end with a real Strands Agent: a scripted model and a fake bhived API."""

from __future__ import annotations

import logging

import pytest
from strands import Agent

from st_testkit import QUERY_RESPONSE, WRITE_RESPONSE, FakeAPI, ScriptedModel, error, make_clients, ok
from strands_bhived import BhivedPlugin, bhived_tools

QUESTION = "boto3 raises NoRegionError inside my Lambda. How do I fix it?"


def build(api: FakeAPI, model: ScriptedModel, *, read_only: bool = False, **plugin_kwargs) -> Agent:
    clients = make_clients(api)
    return Agent(
        model=model,
        tools=bhived_tools(clients=clients, read_only=read_only),
        plugins=[BhivedPlugin(clients=clients, **plugin_kwargs)],
        system_prompt="You are a careful AWS assistant.",
        callback_handler=None,
    )


def test_lessons_reach_the_model_but_never_the_stored_history() -> None:
    api = FakeAPI(ok(QUERY_RESPONSE))
    model = ScriptedModel(["Pass region_name to the boto3 client."])
    agent = build(api, model, read_only=True)
    agent(QUESTION)

    seen = model.text_seen(0)
    assert QUESTION in seen
    assert "## Shared lessons (from bhived)" in seen
    assert "boto3: pass region_name explicitly in Lambda" in seen
    assert "Do NOT create a boto3 client per request" in seen
    assert "query_id" not in seen  # read-only tools: no write tool to pass it to
    assert model.calls[0]["system_prompt"] == "You are a careful AWS assistant."

    assert not any("Shared lessons" in str(message) for message in agent.messages)
    assert api.paths() == ["/v2/query"]
    assert api.body()["query"] == QUESTION
    assert api.body()["top_k"] == 3


def test_write_tool_call_links_the_query_id() -> None:
    api = FakeAPI(ok(QUERY_RESPONSE), ok(WRITE_RESPONSE))
    write = {
        "tool": "bhived_write_instruction",
        "input": {
            "title": "boto3: pass region_name in Lambda",
            "text": "**Context:** boto3 1.35\n**Solution:** pass region_name\n**Verified:** handler runs",
            "query_id": "q-st-1",
        },
    }
    model = ScriptedModel([write, "Done."])
    agent = build(api, model)
    agent(QUESTION)

    assert "query_id: q-st-1" in model.text_seen(0)
    assert api.paths() == ["/v2/query", "/v1/memories"]
    assert api.body(1)["query_id"] == "q-st-1"
    assert api.body(1)["type"] == "instruction"
    assert api.requests[1].headers["Idempotency-Key"]
    tool_results = [
        block["toolResult"]
        for message in agent.messages
        for block in message["content"]
        if isinstance(block, dict) and "toolResult" in block
    ]
    assert "Lesson created." in str(tool_results[0]["content"])
    assert not any("Shared lessons" in str(message) for message in agent.messages)


def test_a_second_turn_gets_fresh_lessons_and_no_leftovers() -> None:
    other = dict(QUERY_RESPONSE, query_id="q-st-2")
    api = FakeAPI(ok(QUERY_RESPONSE), ok(other))
    model = ScriptedModel(["First answer.", "Second answer."])
    agent = build(api, model, read_only=True)
    agent(QUESTION)
    agent("And how do I set the region for the S3 client in tests?")

    assert api.paths() == ["/v2/query", "/v2/query"]
    assert model.text_seen(1).count("## Shared lessons (from bhived)") == 1


def test_failed_recall_lets_the_agent_answer(caplog: pytest.LogCaptureFixture) -> None:
    api = FakeAPI(error(403, "Invalid or inactive API key"))
    model = ScriptedModel(["Answer without lessons."])
    with caplog.at_level(logging.WARNING, logger="strands_bhived.plugin"):
        build(api, model, read_only=True)(QUESTION)
    assert "Shared lessons" not in model.text_seen(0)
    assert "bhived recall skipped (AuthenticationError)" in caplog.text
    assert "bhv_test_key" not in caplog.text


def test_short_messages_skip_recall() -> None:
    api = FakeAPI()
    model = ScriptedModel(["You're welcome."])
    build(api, model, read_only=True)("thanks")
    assert api.requests == []


def test_options_are_sent() -> None:
    api = FakeAPI(ok(QUERY_RESPONSE))
    model = ScriptedModel(["ok"])
    build(api, model, read_only=True, top_k=6, scope="global_only", context="Python 3.12, boto3 1.35")(QUESTION)
    assert api.body() == {
        "query": QUESTION,
        "context": "Python 3.12, boto3 1.35",
        "top_k": 6,
        "scope": "global_only",
        "include_warnings": True,
        "include_episodes": False,
        "include_disputed": False,
    }


@pytest.mark.asyncio
async def test_invoke_async() -> None:
    api = FakeAPI(ok(QUERY_RESPONSE))
    model = ScriptedModel(["Pass region_name."])
    await build(api, model, read_only=True).invoke_async(QUESTION)
    assert "Shared lessons" in model.text_seen(0)


@pytest.mark.parametrize("kwargs", [{"top_k": 0}, {"scope": "everyone"}, {"max_tokens": 10}])
def test_invalid_options(kwargs) -> None:
    with pytest.raises(ValueError):
        BhivedPlugin(**kwargs)
