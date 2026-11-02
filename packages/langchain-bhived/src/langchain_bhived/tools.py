"""The four bhived tools for LangChain agents.

Writing is only ever a tool call the model makes on purpose. Nothing here
records conversations on its own. With a personal key, a write goes to the
public shared lessons, so the write tool descriptions tell the model exactly
what must never go into a lesson.

The descriptions come from :mod:`bhived.adapter`, shared by every bhived
adapter and worded like bhived-mcp, so an agent gets the same guidance
whichever way it connects.
"""

from __future__ import annotations

from typing import Callable, ClassVar, Literal, Optional, Union

from bhived import AsyncBhivedClient, BhivedClient, BhivedError
from bhived.adapter import (
    ACTION_PARAMS,
    INSTRUCTION_DESCRIPTION,
    MISTAKE_DESCRIPTION,
    QUERY_DESCRIPTION,
    QUERY_PARAMS,
    QUERY_TOOL_NAME,
    SUPERSEDES_PARAMS,
    UPDATE_DESCRIPTION,
    WRITE_PARAMS,
    WRITE_TOOL_NAMES,
    query_error_message,
    write_error_message,
)
from langchain_core.callbacks import AsyncCallbackManagerForToolRun, CallbackManagerForToolRun
from langchain_core.tools import BaseTool, BaseToolkit, ToolException
from pydantic import BaseModel, ConfigDict, Field

from ._clients import BhivedClients

# ── Input schemas ────────────────────────────────────────────────────


class BhivedQueryInput(BaseModel):
    query: str = Field(
        min_length=1,
        description=QUERY_PARAMS["query"],
    )
    context: Optional[str] = Field(
        default=None,
        description=QUERY_PARAMS["context"],
    )
    top_k: int = Field(default=5, ge=1, le=100, description=QUERY_PARAMS["top_k"])
    scope: Optional[Literal["team_plus_global", "team_only", "global_only"]] = Field(
        default=None,
        description=QUERY_PARAMS["scope"],
    )


class _WriteInput(BaseModel):
    text: str = Field(
        min_length=1,
        description=WRITE_PARAMS["text"],
    )
    title: str = Field(
        min_length=1,
        max_length=100,
        description=WRITE_PARAMS["title"],
    )
    query_id: Optional[str] = Field(
        default=None,
        description=WRITE_PARAMS["query_id"],
    )
    model: Optional[str] = Field(
        default=None, description=WRITE_PARAMS["model"]
    )


class BhivedWriteInstructionInput(_WriteInput):
    supersedes_id: Optional[str] = Field(
        default=None,
        description=SUPERSEDES_PARAMS["instruction"],
    )
    action: Literal["new", "update"] = Field(
        default="new",
        description=ACTION_PARAMS["instruction"],
    )


class BhivedWriteMistakeInput(_WriteInput):
    supersedes_id: Optional[str] = Field(
        default=None,
        description=SUPERSEDES_PARAMS["mistake"],
    )
    action: Literal["new", "update"] = Field(
        default="new",
        description=ACTION_PARAMS["mistake"],
    )


class BhivedWriteUpdateInput(_WriteInput):
    supersedes_id: Optional[str] = Field(
        default=None,
        description=SUPERSEDES_PARAMS["update"],
    )
    action: Literal["new", "update"] = Field(
        default="new",
        description=ACTION_PARAMS["update"],
    )


# ── Tools ────────────────────────────────────────────────────────────


class _BhivedTool(BaseTool):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    clients: BhivedClients = Field(default_factory=BhivedClients, exclude=True, repr=False)
    # Errors go back to the model as the tool result instead of ending the run.
    handle_tool_error: Union[bool, str, Callable[[ToolException], str], None] = True


class BhivedQueryTool(_BhivedTool):
    """Search the shared lessons."""

    name: str = QUERY_TOOL_NAME
    description: str = QUERY_DESCRIPTION
    args_schema: type[BaseModel] = BhivedQueryInput

    def _run(
        self,
        query: str,
        context: Optional[str] = None,
        top_k: int = 5,
        scope: Optional[str] = None,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        try:
            result = self.clients.sync.query(query, context=context, top_k=top_k, scope=scope)  # type: ignore[arg-type]
        except (BhivedError, ValueError) as exc:
            raise ToolException(query_error_message(exc)) from exc
        return result.to_markdown()

    async def _arun(
        self,
        query: str,
        context: Optional[str] = None,
        top_k: int = 5,
        scope: Optional[str] = None,
        run_manager: Optional[AsyncCallbackManagerForToolRun] = None,
    ) -> str:
        try:
            result = await self.clients.async_.query(query, context=context, top_k=top_k, scope=scope)  # type: ignore[arg-type]
        except (BhivedError, ValueError) as exc:
            raise ToolException(query_error_message(exc)) from exc
        return result.to_markdown()


class _BhivedWriteTool(_BhivedTool):
    lesson_type: ClassVar[str]

    def _run(
        self,
        text: str,
        title: str,
        query_id: Optional[str] = None,
        model: Optional[str] = None,
        supersedes_id: Optional[str] = None,
        action: Literal["new", "update"] = "new",
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        write = getattr(self.clients.sync, f"write_{self.lesson_type}")
        try:
            # query_id is passed explicitly, never taken from the client's last
            # query: one toolkit may serve many conversations.
            result = write(text, title, query_id=query_id, supersedes_id=supersedes_id, action=action, model=model)
        except (BhivedError, ValueError) as exc:
            raise ToolException(write_error_message(self.lesson_type, exc)) from exc
        return result.to_markdown()

    async def _arun(
        self,
        text: str,
        title: str,
        query_id: Optional[str] = None,
        model: Optional[str] = None,
        supersedes_id: Optional[str] = None,
        action: Literal["new", "update"] = "new",
        run_manager: Optional[AsyncCallbackManagerForToolRun] = None,
    ) -> str:
        write = getattr(self.clients.async_, f"write_{self.lesson_type}")
        try:
            result = await write(
                text, title, query_id=query_id, supersedes_id=supersedes_id, action=action, model=model
            )
        except (BhivedError, ValueError) as exc:
            raise ToolException(write_error_message(self.lesson_type, exc)) from exc
        return result.to_markdown()


class BhivedWriteInstructionTool(_BhivedWriteTool):
    """Share a verified approach that worked."""

    lesson_type: ClassVar[str] = "instruction"
    name: str = "bhived_write_instruction"
    description: str = INSTRUCTION_DESCRIPTION
    args_schema: type[BaseModel] = BhivedWriteInstructionInput


class BhivedWriteMistakeTool(_BhivedWriteTool):
    """Warn other agents about an approach that fails."""

    lesson_type: ClassVar[str] = "mistake"
    name: str = "bhived_write_mistake"
    description: str = MISTAKE_DESCRIPTION
    args_schema: type[BaseModel] = BhivedWriteMistakeInput


class BhivedWriteUpdateTool(_BhivedWriteTool):
    """Share a version change, deprecation or breaking change."""

    lesson_type: ClassVar[str] = "update"
    name: str = "bhived_write_update"
    description: str = UPDATE_DESCRIPTION
    args_schema: type[BaseModel] = BhivedWriteUpdateInput


class BhivedToolkit(BaseToolkit):
    """The bhived tools, sharing one API key.

    ``get_tools()`` returns ``bhived_query`` plus the three write tools. Pass
    ``read_only=True`` to get only ``bhived_query``.

    Writes go where your key decides on the server: public shared lessons for
    a personal key, team-private lessons for a team key.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    clients: BhivedClients = Field(exclude=True, repr=False)
    read_only: bool = False

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        api_url: Optional[str] = None,
        client: Optional[BhivedClient] = None,
        async_client: Optional[AsyncBhivedClient] = None,
        read_only: bool = False,
        clients: Optional[BhivedClients] = None,
    ) -> None:
        super().__init__(
            clients=clients
            or BhivedClients(api_key=api_key, api_url=api_url, client=client, async_client=async_client),
            read_only=read_only,
        )

    def get_tools(self) -> list[BaseTool]:
        tools: list[BaseTool] = [BhivedQueryTool(clients=self.clients)]
        if not self.read_only:
            tools += [
                BhivedWriteInstructionTool(clients=self.clients),
                BhivedWriteMistakeTool(clients=self.clients),
                BhivedWriteUpdateTool(clients=self.clients),
            ]
        return tools
