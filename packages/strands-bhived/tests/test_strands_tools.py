from __future__ import annotations

import httpx
import pytest

from st_testkit import QUERY_RESPONSE, TEST_KEY, WRITE_RESPONSE, FakeAPI, error, make_clients, ok
from strands_bhived import BhivedPlugin, bhived_tools

LESSON = {
    "text": "**Context:** boto3 1.35\n**Solution:** pass region_name\n**Verified:** handler runs",
    "title": "boto3: pass region_name in Lambda",
}


def tools_by_name(api: FakeAPI, **kwargs) -> dict:
    return {t.tool_name: t for t in bhived_tools(clients=make_clients(api), **kwargs)}


def test_names_and_read_only() -> None:
    assert list(tools_by_name(FakeAPI())) == [
        "bhived_query",
        "bhived_write_instruction",
        "bhived_write_mistake",
        "bhived_write_update",
    ]
    assert list(tools_by_name(FakeAPI(), read_only=True)) == ["bhived_query"]


def test_write_descriptions_carry_the_privacy_rules() -> None:
    for name, t in tools_by_name(FakeAPI()).items():
        description = t.tool_spec["description"]
        if name == "bhived_query":
            assert "query_id" in description
            continue
        for phrase in ("secrets", "credentials", "customer", "proprietary code", "PUBLIC shared lessons", "team"):
            assert phrase in description, (name, phrase)


def test_every_parameter_has_a_description() -> None:
    # Guards the Python 3.10 case where Optional parameters can lose their Annotated text.
    for name, t in tools_by_name(FakeAPI()).items():
        for param, spec in t.tool_spec["inputSchema"]["json"]["properties"].items():
            assert spec.get("description"), f"{name}.{param} has no description"


@pytest.mark.asyncio
async def test_query_tool_output() -> None:
    api = FakeAPI(ok(QUERY_RESPONSE))
    output = await tools_by_name(api)["bhived_query"](query="boto3 NoRegionError Lambda", top_k=2)
    assert "boto3: pass region_name explicitly in Lambda" in output
    assert "query_id: `q-st-1`" in output
    assert api.body()["top_k"] == 2


@pytest.mark.asyncio
async def test_write_tools_send_only_the_query_id_they_get() -> None:
    api = FakeAPI(ok(QUERY_RESPONSE), ok(WRITE_RESPONSE), ok(WRITE_RESPONSE))
    tools = tools_by_name(api)
    await tools["bhived_query"](query="boto3 NoRegionError Lambda")

    output = await tools["bhived_write_mistake"](**LESSON, query_id="q-st-1")
    assert "Lesson created." in output
    assert api.body()["type"] == "mistake"
    assert api.body()["query_id"] == "q-st-1"

    await tools["bhived_write_update"](**LESSON)
    assert "query_id" not in api.body()


@pytest.mark.asyncio
async def test_errors_come_back_as_text() -> None:
    duplicate = error(409, {"error": "duplicate_memory", "duplicate_of": "m-old", "jaccard_similarity": 0.9})
    api = FakeAPI(duplicate, httpx.ConnectError, httpx.ConnectError, error(403, "Invalid or inactive API key"))
    tools = tools_by_name(api)
    assert "NOT saved" in await tools["bhived_write_instruction"](**LESSON)
    assert "outcome unknown" in await tools["bhived_write_instruction"](**LESSON)
    output = await tools["bhived_query"](query="anything at all")
    assert output.startswith("Error querying bhived")
    assert TEST_KEY not in output


def test_plugin_and_tools_build_clients_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BHIVED_API_KEY", TEST_KEY)
    plugin = BhivedPlugin()
    assert plugin.clients.config.api_key == TEST_KEY
    assert TEST_KEY not in repr(plugin.clients)
    assert bhived_tools()[0].tool_name == "bhived_query"
