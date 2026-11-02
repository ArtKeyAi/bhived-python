"""End to end with LangChain's create_agent: a scripted model, a fake bhived API."""

from __future__ import annotations

import pytest
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from langchain_bhived import BhivedMiddleware, BhivedToolkit
from lc_testkit import QUERY_RESPONSE, WRITE_RESPONSE, FakeAPI, ScriptedChatModel, make_clients, ok

QUESTION = "Pydantic v2 warns that class Config is deprecated. What should I use?"


def scripted_model() -> ScriptedChatModel:
    write_call = {
        "name": "bhived_write_instruction",
        "args": {
            "title": "pydantic 2: replace class Config with model_config",
            "text": "**Context:** pydantic 2.9\n**Solution:** model_config = ConfigDict(...)\n**Verified:** tests pass",
            "query_id": "q-lc-1",
        },
        "id": "call_1",
        "type": "tool_call",
    }
    return ScriptedChatModel(
        responses=[
            AIMessage(content="", tool_calls=[write_call]),
            AIMessage(content="Use model_config = ConfigDict(...)."),
        ]
    )


def build(api: FakeAPI, model: ScriptedChatModel):
    clients = make_clients(api)
    return create_agent(
        model,
        tools=BhivedToolkit(clients=clients).get_tools(),
        system_prompt="You are a careful Python assistant.",
        middleware=[BhivedMiddleware(client=clients.sync, async_client=clients.async_)],
    )


def check_run(api: FakeAPI, model: ScriptedChatModel, result: dict) -> None:
    # One recall for the user turn, then the write the model chose to make.
    assert api.paths() == ["/v2/query", "/v1/memories"]
    assert api.body(1)["query_id"] == "q-lc-1"

    first_call = model.seen[0]
    assert isinstance(first_call[0], SystemMessage)
    system_text = str(first_call[0].content)
    assert "You are a careful Python assistant." in system_text
    assert "## Shared lessons (from bhived)" in system_text
    assert "query_id: q-lc-1" in system_text
    assert "Shared lessons" in str(model.seen[1][0].content)  # the second model call gets it too, from the cache

    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert "Lesson created." in str(tool_messages[0].content)
    assert result["messages"][-1].content == "Use model_config = ConfigDict(...)."
    # The lessons block was never written into the conversation state.
    assert not any("Shared lessons" in str(m.content) for m in result["messages"])


def test_create_agent_invoke() -> None:
    api = FakeAPI(ok(QUERY_RESPONSE), ok(WRITE_RESPONSE))
    model = scripted_model()
    result = build(api, model).invoke({"messages": [HumanMessage(QUESTION)]})
    check_run(api, model, result)


@pytest.mark.asyncio
async def test_create_agent_ainvoke() -> None:
    api = FakeAPI(ok(QUERY_RESPONSE), ok(WRITE_RESPONSE))
    model = scripted_model()
    result = await build(api, model).ainvoke({"messages": [HumanMessage(QUESTION)]})
    check_run(api, model, result)
