from __future__ import annotations

import httpx
import pytest

from af_testkit import QUERY_RESPONSE, TEST_KEY, WRITE_RESPONSE, FakeAPI, error, make_clients, ok, text_of
from agent_framework_bhived import BhivedContextProvider, bhived_tools

LESSON = {
    "text": "**Context:** azure-identity 1.19\n**Solution:** federated credential\n**Verified:** CI green",
    "title": "azure-identity: federated credential for GitHub Actions",
}


def tools_by_name(api: FakeAPI, **kwargs) -> dict:
    return {t.name: t for t in bhived_tools(clients=make_clients(api), **kwargs)}


def test_names_read_only_and_approval_mode() -> None:
    assert list(tools_by_name(FakeAPI())) == [
        "bhived_query",
        "bhived_write_instruction",
        "bhived_write_mistake",
        "bhived_write_update",
    ]
    assert list(tools_by_name(FakeAPI(), read_only=True)) == ["bhived_query"]
    gated = tools_by_name(FakeAPI(), write_approval_mode="always_require")
    assert gated["bhived_write_update"].approval_mode == "always_require"
    assert gated["bhived_query"].approval_mode != "always_require"


def test_descriptions_and_schema() -> None:
    tools = tools_by_name(FakeAPI())
    for name, t in tools.items():
        if name == "bhived_query":
            assert "query_id" in t.description
            continue
        for phrase in ("secrets", "credentials", "customer", "proprietary code", "PUBLIC shared lessons", "team"):
            assert phrase in t.description, (name, phrase)
    schema = tools["bhived_write_mistake"].parameters()
    assert set(schema["properties"]) == {"text", "title", "query_id", "model", "supersedes_id", "action"}
    assert set(schema["required"]) == {"text", "title"}
    assert "YOUR OWN earlier mistake" in schema["properties"]["supersedes_id"]["description"]


@pytest.mark.asyncio
async def test_query_and_writes() -> None:
    api = FakeAPI(ok(QUERY_RESPONSE), ok(WRITE_RESPONSE), ok(WRITE_RESPONSE))
    tools = tools_by_name(api)
    output = await tools["bhived_query"].invoke(arguments={"query": "DefaultAzureCredential GitHub Actions", "top_k": 2})
    assert "query_id: `q-af-1`" in text_of(output)
    assert api.body()["top_k"] == 2

    output = await tools["bhived_write_update"].invoke(arguments={**LESSON, "query_id": "q-af-1"})
    assert "Lesson created." in text_of(output)
    assert api.body()["type"] == "update"
    assert api.body()["query_id"] == "q-af-1"

    await tools["bhived_write_instruction"].invoke(arguments=LESSON)
    assert "query_id" not in api.body()  # never borrowed from the client's last query


@pytest.mark.asyncio
async def test_errors_come_back_as_text() -> None:
    duplicate = error(409, {"error": "duplicate_memory", "duplicate_of": "m-old", "jaccard_similarity": 0.9})
    api = FakeAPI(duplicate, httpx.ConnectError, httpx.ConnectError, error(403, "Invalid or inactive API key"))
    tools = tools_by_name(api)
    assert "NOT saved" in text_of(await tools["bhived_write_mistake"].invoke(arguments=LESSON))
    assert "outcome unknown" in text_of(await tools["bhived_write_mistake"].invoke(arguments=LESSON))
    output = text_of(await tools["bhived_query"].invoke(arguments={"query": "anything at all"}))
    assert "Error querying bhived" in output
    assert TEST_KEY not in output


def test_built_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BHIVED_API_KEY", TEST_KEY)
    provider = BhivedContextProvider()
    assert provider.source_id == "bhived"
    assert provider.clients.config.api_key == TEST_KEY
    assert TEST_KEY not in repr(provider.clients)
    assert bhived_tools()[0].name == "bhived_query"
