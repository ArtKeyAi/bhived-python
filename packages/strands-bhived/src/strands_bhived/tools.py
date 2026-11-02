"""The four bhived tools as Strands ``@tool`` functions.

Writing is only ever a tool call the model makes on purpose. With a personal
key a write goes to the public shared lessons, so the write tool descriptions
spell out what must never go into a lesson. Errors come back to the model as
the tool result instead of ending the run.
"""

# No `from __future__ import annotations` here: the @tool decorator reads the
# parameter annotations, and the write tools build theirs from a local variable.
from typing import Annotated, Any, Literal, Optional

from bhived import AsyncBhivedClient, BhivedClient, BhivedError
from bhived.adapter import (
    ACTION_PARAMS,
    QUERY_DESCRIPTION,
    QUERY_PARAMS,
    QUERY_TOOL_NAME,
    SUPERSEDES_PARAMS,
    WRITE_DESCRIPTIONS,
    WRITE_PARAMS,
    query_error_message,
    write_error_message,
)
from strands import tool

from ._clients import BhivedClients

Scope = Literal["team_plus_global", "team_only", "global_only"]


def bhived_tools(
    *,
    api_key: Optional[str] = None,
    api_url: Optional[str] = None,
    client: Optional[BhivedClient] = None,
    async_client: Optional[AsyncBhivedClient] = None,
    clients: Optional[BhivedClients] = None,
    read_only: bool = False,
) -> list[Any]:
    """``bhived_query`` plus the three write tools, ready for ``Agent(tools=...)``.

    Pass ``read_only=True`` to get only ``bhived_query``. Writes go where your
    key decides on the server: public shared lessons for a personal key,
    team-private lessons for a team key.
    """
    clients = clients or BhivedClients(api_key=api_key, api_url=api_url, client=client, async_client=async_client)

    @tool(name=QUERY_TOOL_NAME, description=QUERY_DESCRIPTION)
    async def bhived_query(
        query: Annotated[str, QUERY_PARAMS["query"]],
        context: Annotated[Optional[str], QUERY_PARAMS["context"]] = None,
        top_k: Annotated[int, QUERY_PARAMS["top_k"]] = 5,
        scope: Annotated[Optional[Scope], QUERY_PARAMS["scope"]] = None,
    ) -> str:
        try:
            result = await clients.async_.query(query, context=context, top_k=top_k, scope=scope)
        except (BhivedError, ValueError) as exc:
            return query_error_message(exc)
        return result.to_markdown()

    tools: list[Any] = [bhived_query]
    if not read_only:
        tools += [_write_tool(clients, lesson_type) for lesson_type in ("instruction", "mistake", "update")]
    return tools


def _write_tool(clients: BhivedClients, lesson_type: str) -> Any:
    @tool(name=f"bhived_write_{lesson_type}", description=WRITE_DESCRIPTIONS[lesson_type])
    async def write(
        text: Annotated[str, WRITE_PARAMS["text"]],
        title: Annotated[str, WRITE_PARAMS["title"]],
        query_id: Annotated[Optional[str], WRITE_PARAMS["query_id"]] = None,
        model: Annotated[Optional[str], WRITE_PARAMS["model"]] = None,
        supersedes_id: Annotated[Optional[str], SUPERSEDES_PARAMS[lesson_type]] = None,
        action: Annotated[Literal["new", "update"], ACTION_PARAMS[lesson_type]] = "new",
    ) -> str:
        method = getattr(clients.async_, f"write_{lesson_type}")
        try:
            # query_id is passed explicitly, never taken from the client's last
            # query: one set of tools may serve many conversations.
            result = await method(
                text, title, query_id=query_id, supersedes_id=supersedes_id, action=action, model=model
            )
        except (BhivedError, ValueError) as exc:
            return write_error_message(lesson_type, exc)
        return result.to_markdown()

    return write
