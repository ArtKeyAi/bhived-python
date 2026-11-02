"""Recall shared lessons before each model call.

``BhivedMiddleware`` hooks ``wrap_model_call`` / ``awrap_model_call`` (the
LangChain v1 ``AgentMiddleware`` API). Before the model runs it searches
bhived with the latest user message and appends a short "Shared lessons"
block to the system message, for that call only. Nothing is stored in the
agent state, and nothing is ever written to bhived from here: writing is
left to the explicit tools in :class:`~langchain_bhived.BhivedToolkit`.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Optional, Sequence

from bhived import SCOPES, AsyncBhivedClient, BhivedClient, BhivedError, QueryResult
from bhived.adapter import WRITE_TOOL_NAMES, FailureLog, RecallCache, clean_query
from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from ._clients import BhivedClients

logger = logging.getLogger(__name__)

MIN_MAX_TOKENS = 100


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    parts: list[str] = []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
                parts.append(block["text"])
    return "\n".join(parts)


def latest_user_text(messages: Sequence[BaseMessage]) -> Optional[str]:
    """Text of the most recent human message, or None if there is none."""
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return _text_of(message.content)
    return None


def _tool_names(tools: Sequence[Any]) -> set[str]:
    names: set[str] = set()
    for tool in tools:
        name = tool.get("name") if isinstance(tool, dict) else getattr(tool, "name", None)
        if isinstance(name, str):
            names.add(name)
    return names


class BhivedMiddleware(AgentMiddleware):
    """Adds lessons other agents already verified to the system prompt.

    Use it with ``create_agent``::

        agent = create_agent(model, tools=[...], middleware=[BhivedMiddleware()])

    Args:
        api_key: bhived API key. Defaults to ``BHIVED_API_KEY`` or the key
            saved by ``npx bhived setup``.
        api_url: API base URL. Defaults to ``BHIVED_API_URL`` or
            ``https://mcp.bhived.ai``.
        client: A ready-made :class:`bhived.BhivedClient` (used for ``invoke``).
        async_client: A ready-made :class:`bhived.AsyncBhivedClient` (used for
            ``ainvoke``).
        clients: A :class:`BhivedClients` to share with a ``BhivedToolkit``.
        top_k: How many results to ask for per tier (1-100).
        scope: ``team_plus_global`` (server default), ``team_only`` or
            ``global_only``.
        max_tokens: Rough upper bound for the added block, counted as about
            four characters per token.
        context: Optional fixed context sent with every query, such as
            ``"Python 3.12, FastAPI, Postgres"``.
        include_warnings: Also add known mistakes (recommended).
        min_query_chars: Skip recall for shorter user messages ("thanks", "ok").
        max_query_chars: Only the first this-many characters of the user
            message are sent as the query.
        cache_size: How many recent queries to remember. An agent calls the
            model several times per user turn (after each tool call); the
            cache makes that one bhived query instead of several. 0 disables it.
        cache_ttl: Seconds a cached result stays valid.
        build_query: Optional function that turns a ``ModelRequest`` into the
            query text. Return None to skip recall for that call.
        raise_on_error: By default a failed recall is logged and the model
            call goes ahead without lessons. Set True to raise instead.
    """

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        api_url: Optional[str] = None,
        client: Optional[BhivedClient] = None,
        async_client: Optional[AsyncBhivedClient] = None,
        clients: Optional[BhivedClients] = None,
        top_k: int = 3,
        scope: Optional[str] = None,
        max_tokens: int = 600,
        context: Optional[str] = None,
        include_warnings: bool = True,
        min_query_chars: int = 8,
        max_query_chars: int = 2000,
        cache_size: int = 128,
        cache_ttl: float = 600.0,
        build_query: Optional[Callable[[ModelRequest], Optional[str]]] = None,
        raise_on_error: bool = False,
    ) -> None:
        super().__init__()
        if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 100:
            raise ValueError("top_k must be an integer from 1 to 100")
        if scope is not None and scope not in SCOPES:
            raise ValueError(f"scope must be one of {', '.join(SCOPES)}")
        if max_tokens < MIN_MAX_TOKENS:
            raise ValueError(f"max_tokens must be at least {MIN_MAX_TOKENS}")
        self.clients = clients or BhivedClients(
            api_key=api_key, api_url=api_url, client=client, async_client=async_client
        )
        self.top_k = top_k
        self.scope = scope
        self.max_tokens = max_tokens
        self.context = context
        self.include_warnings = include_warnings
        self.min_query_chars = min_query_chars
        self.max_query_chars = max_query_chars
        self.cache_size = cache_size
        self.cache_ttl = cache_ttl
        self.build_query = build_query
        self.raise_on_error = raise_on_error
        self._cache = RecallCache(cache_size, cache_ttl)
        self._failures = FailureLog(logger)

    # ── LangChain hooks ──────────────────────────────────────────────

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        query = self._query_text(request)
        if query is None:
            return handler(request)
        result = self._cache.get(query)
        if result is None:
            try:
                result = self.clients.sync.query(query, **self._query_kwargs())
            except BhivedError as exc:
                self._recall_failed(exc)
            else:
                self._cache.put(query, result)
        return handler(self._with_lessons(request, result))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        query = self._query_text(request)
        if query is None:
            return await handler(request)
        result = self._cache.get(query)
        if result is None:
            try:
                result = await self.clients.async_.query(query, **self._query_kwargs())
            except BhivedError as exc:
                self._recall_failed(exc)
            else:
                self._cache.put(query, result)
        return await handler(self._with_lessons(request, result))

    # ── Helpers ──────────────────────────────────────────────────────

    def _query_text(self, request: ModelRequest) -> Optional[str]:
        text = self.build_query(request) if self.build_query else latest_user_text(request.messages)
        return clean_query(text, min_chars=self.min_query_chars, max_chars=self.max_query_chars)

    def _query_kwargs(self) -> dict[str, Any]:
        # Episodes and disputed pairs are not shown in the block, so don't ask for them.
        return {
            "context": self.context,
            "top_k": self.top_k,
            "scope": self.scope,
            "include_warnings": self.include_warnings,
            "include_episodes": False,
            "include_disputed": False,
        }

    def _with_lessons(self, request: ModelRequest, result: Optional[QueryResult]) -> ModelRequest:
        if result is None:
            return request
        block = result.as_context(
            max_tokens=self.max_tokens,
            include_warnings=self.include_warnings,
            mention_write_tools=bool(_tool_names(request.tools) & set(WRITE_TOOL_NAMES)),
        )
        if not block:
            return request
        existing = request.system_message
        if existing is None:
            system = SystemMessage(content=block)
        else:
            system = SystemMessage(content=[*existing.content_blocks, {"type": "text", "text": block}])
        return request.override(system_message=system)

    def _recall_failed(self, exc: BhivedError) -> None:
        if self.raise_on_error:
            raise exc
        self._failures.report(exc)
