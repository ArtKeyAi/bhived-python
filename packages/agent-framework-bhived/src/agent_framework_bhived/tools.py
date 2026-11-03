"""The four bhived tools as Agent Framework function tools.

Writing is only ever a tool call the model makes on purpose. With a personal
key a write goes to the public shared lessons, so the write tool descriptions
spell out what must never go into a lesson. If you want a person to confirm
every write, pass ``write_approval_mode="always_require"``. Errors come back to
the model as the tool result instead of ending the run.

Each tool gets an explicit pydantic input model instead of relying on
``Annotated`` hints. On Python 3.10, ``typing.get_type_hints`` wraps a
parameter that defaults to ``None`` in an extra ``Optional[...]``, which hides
the ``Annotated`` description, so every optional parameter would reach the
model without one.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from agent_framework import FunctionTool, tool
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
from pydantic import BaseModel, Field, create_model

from ._clients import BhivedClients

Scope = Literal["team_plus_global", "team_only", "global_only"]
ApprovalMode = Literal["always_require", "never_require"]


class BhivedQueryInput(BaseModel):
    query: str = Field(min_length=1, description=QUERY_PARAMS["query"])
    context: Optional[str] = Field(default=None, description=QUERY_PARAMS["context"])
    top_k: int = Field(default=5, ge=1, le=100, description=QUERY_PARAMS["top_k"])
    scope: Optional[Scope] = Field(default=None, description=QUERY_PARAMS["scope"])


def _write_input(lesson_type: str) -> type[BaseModel]:
    """The input model for one write tool. Only supersedes_id and action differ by type."""
    return create_model(
        f"BhivedWrite{lesson_type.capitalize()}Input",
        text=(str, Field(min_length=1, description=WRITE_PARAMS["text"])),
        title=(str, Field(min_length=1, max_length=100, description=WRITE_PARAMS["title"])),
        query_id=(Optional[str], Field(default=None, description=WRITE_PARAMS["query_id"])),
        model=(Optional[str], Field(default=None, description=WRITE_PARAMS["model"])),
        supersedes_id=(Optional[str], Field(default=None, description=SUPERSEDES_PARAMS[lesson_type])),
        action=(Literal["new", "update"], Field(default="new", description=ACTION_PARAMS[lesson_type])),
    )


def bhived_tools(
    *,
    api_key: Optional[str] = None,
    api_url: Optional[str] = None,
    client: Optional[BhivedClient] = None,
    async_client: Optional[AsyncBhivedClient] = None,
    clients: Optional[BhivedClients] = None,
    read_only: bool = False,
    write_approval_mode: Optional[ApprovalMode] = None,
) -> list[FunctionTool]:
    """``bhived_query`` plus the three write tools, ready for ``Agent(tools=...)``.

    Pass ``read_only=True`` to get only ``bhived_query``. Writes go where your
    key decides on the server: public shared lessons for a personal key,
    team-private lessons for a team key.
    """
    clients = clients or BhivedClients(api_key=api_key, api_url=api_url, client=client, async_client=async_client)

    async def bhived_query(
        query: str,
        context: Optional[str] = None,
        top_k: int = 5,
        scope: Optional[Scope] = None,
    ) -> str:
        try:
            result = await clients.async_.query(query, context=context, top_k=top_k, scope=scope)
        except (BhivedError, ValueError) as exc:
            return query_error_message(exc)
        return result.to_markdown()

    tools: list[FunctionTool] = [
        tool(bhived_query, name=QUERY_TOOL_NAME, description=QUERY_DESCRIPTION, schema=BhivedQueryInput)
    ]
    if not read_only:
        tools += [
            _write_tool(clients, lesson_type, write_approval_mode)
            for lesson_type in ("instruction", "mistake", "update")
        ]
    return tools


def _write_tool(clients: BhivedClients, lesson_type: str, approval_mode: Optional[ApprovalMode]) -> FunctionTool:
    async def write(
        text: str,
        title: str,
        query_id: Optional[str] = None,
        model: Optional[str] = None,
        supersedes_id: Optional[str] = None,
        action: Literal["new", "update"] = "new",
    ) -> str:
        method: Any = getattr(clients.async_, f"write_{lesson_type}")
        try:
            # query_id is passed explicitly, never taken from the client's last
            # query: one set of tools may serve many conversations.
            result = await method(
                text, title, query_id=query_id, supersedes_id=supersedes_id, action=action, model=model
            )
        except (BhivedError, ValueError) as exc:
            return write_error_message(lesson_type, exc)
        return result.to_markdown()

    return tool(
        write,
        name=f"bhived_write_{lesson_type}",
        description=WRITE_DESCRIPTIONS[lesson_type],
        schema=_write_input(lesson_type),
        approval_mode=approval_mode,
    )
