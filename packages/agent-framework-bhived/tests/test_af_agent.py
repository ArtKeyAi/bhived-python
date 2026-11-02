"""End to end with a real Agent Framework Agent: a scripted chat client and a fake bhived API."""

from __future__ import annotations

import logging

import pytest
from agent_framework import Agent, ContextProvider
from bhived import AuthenticationError

from af_testkit import QUERY_RESPONSE, WRITE_RESPONSE, FakeAPI, ScriptedChatClient, error, make_clients, ok
from agent_framework_bhived import BhivedContextProvider, bhived_tools

QUESTION = "DefaultAzureCredential fails in GitHub Actions. What should CI use?"


def build(api: FakeAPI, client: ScriptedChatClient, *, read_only: bool = False, **provider_kwargs) -> Agent:
    clients = make_clients(api)
    return Agent(
        client=client,
        instructions="You are a careful Azure assistant.",
        tools=bhived_tools(clients=clients, read_only=read_only),
        context_providers=[BhivedContextProvider(clients=clients, **provider_kwargs)],
    )


@pytest.mark.asyncio
async def test_lessons_are_added_to_the_run_instructions() -> None:
    api = FakeAPI(ok(QUERY_RESPONSE))
    client = ScriptedChatClient(["Use a federated credential."])
    agent = build(api, client, read_only=True)
    await agent.run(QUESTION)

    instructions = client.instructions(0)
    assert instructions.startswith("You are a careful Azure assistant.")
    assert "## Shared lessons (from bhived)" in instructions
    assert "DefaultAzureCredential locally and in CI" in instructions
    assert "Do NOT commit a client secret" in instructions
    assert "query_id" not in instructions  # read-only tools
    assert api.paths() == ["/v2/query"]
    assert api.body()["query"] == QUESTION


@pytest.mark.asyncio
async def test_write_tool_call_links_the_query_id() -> None:
    api = FakeAPI(ok(QUERY_RESPONSE), ok(WRITE_RESPONSE))
    write = {
        "tool": "bhived_write_instruction",
        "arguments": {
            "title": "azure-identity: federated credential for GitHub Actions",
            "text": "**Context:** azure-identity 1.19\n**Solution:** federated credential\n**Verified:** CI green",
            "query_id": "q-af-1",
        },
    }
    client = ScriptedChatClient([write, "Done."])
    agent = build(api, client)
    response = await agent.run(QUESTION)

    assert "query_id: q-af-1" in client.instructions(0)
    assert api.paths() == ["/v2/query", "/v1/memories"]
    assert api.body(1)["query_id"] == "q-af-1"
    assert api.requests[1].headers["Idempotency-Key"]
    results = [
        str(content.result)
        for message in client.calls[1]["messages"]
        if message.role == "tool"
        for content in message.contents
        if content.type == "function_result"
    ]
    assert any("Lesson created." in r for r in results)
    assert response.text == "Done."


@pytest.mark.asyncio
async def test_each_run_gets_its_own_block_and_the_session_stores_none() -> None:
    other = dict(QUERY_RESPONSE, query_id="q-af-2")
    api = FakeAPI(ok(QUERY_RESPONSE), ok(other))
    client = ScriptedChatClient(["First.", "Second."])
    agent = build(api, client, read_only=True)
    session = agent.create_session()
    await agent.run(QUESTION, session=session)
    await agent.run("And how do I scope the federated credential to one branch?", session=session)

    assert client.instructions(1).count("## Shared lessons (from bhived)") == 1
    assert "Shared lessons" not in str(session.state)


def test_nothing_runs_after_a_run() -> None:
    # No automatic capture: the provider must not override after_run.
    assert BhivedContextProvider.after_run is ContextProvider.after_run


@pytest.mark.asyncio
async def test_failed_recall_lets_the_run_continue(caplog: pytest.LogCaptureFixture) -> None:
    api = FakeAPI(error(403, "Invalid or inactive API key"))
    client = ScriptedChatClient(["Answer without lessons."])
    with caplog.at_level(logging.WARNING, logger="agent_framework_bhived.provider"):
        await build(api, client, read_only=True).run(QUESTION)
    assert "Shared lessons" not in client.instructions(0)
    assert "bhived recall skipped (AuthenticationError)" in caplog.text
    assert "bhv_test_key" not in caplog.text


@pytest.mark.asyncio
async def test_raise_on_error() -> None:
    api = FakeAPI(error(403, "Invalid or inactive API key"))
    with pytest.raises(AuthenticationError):
        await build(api, ScriptedChatClient(["x"]), read_only=True, raise_on_error=True).run(QUESTION)


@pytest.mark.asyncio
async def test_short_messages_skip_and_options_are_sent() -> None:
    api = FakeAPI(ok(QUERY_RESPONSE))
    client = ScriptedChatClient(["You're welcome.", "ok"])
    agent = build(api, client, read_only=True, top_k=4, scope="team_only", context="Python 3.12, azure-identity 1.19")
    await agent.run("thanks")
    assert api.requests == []
    await agent.run(QUESTION)
    assert api.body() == {
        "query": QUESTION,
        "context": "Python 3.12, azure-identity 1.19",
        "top_k": 4,
        "scope": "team_only",
        "include_warnings": True,
        "include_episodes": False,
        "include_disputed": False,
    }


@pytest.mark.parametrize("kwargs", [{"top_k": 0}, {"scope": "everyone"}, {"max_tokens": 10}])
def test_invalid_options(kwargs) -> None:
    with pytest.raises(ValueError):
        BhivedContextProvider(**kwargs)
