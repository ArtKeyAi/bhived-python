"""A context provider that recalls shared lessons before each run.

``BhivedContextProvider`` implements ``before_run``: it searches bhived with
the latest user message and adds a short "Shared lessons" block to that run's
instructions. Instructions live in the run's ``SessionContext``, so nothing is
stored in the session.

There is deliberately no ``after_run``. The provider never captures anything
from a conversation. Writing a lesson is left to the explicit function tools
from :func:`agent_framework_bhived.bhived_tools`.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional, Sequence

from agent_framework import AgentSession, ContextProvider, Message, SessionContext
from bhived import SCOPES, AsyncBhivedClient, BhivedClient, BhivedError
from bhived.adapter import WRITE_TOOL_NAMES, FailureLog, RecallCache, clean_query

from ._clients import BhivedClients

logger = logging.getLogger(__name__)

DEFAULT_SOURCE_ID = "bhived"
MIN_MAX_TOKENS = 100


def latest_user_text(messages: Sequence[Message]) -> Optional[str]:
    """Text of the most recent user message that has text."""
    for message in reversed(messages):
        if message.role == "user" and message.text and message.text.strip():
            return message.text
    return None


def _agent_tool_names(agent: Any, context: SessionContext) -> set[str]:
    options = getattr(agent, "default_options", None) or {}
    tools = list(options.get("tools") or []) + list(context.tools or [])
    return {name for name in (getattr(t, "name", None) for t in tools) if isinstance(name, str)}


class BhivedContextProvider(ContextProvider):
    """Adds lessons other agents already verified to each run's instructions.

    Use it with ``Agent(..., context_providers=[BhivedContextProvider()])``.

    Args:
        source_id: Provider id used for attribution. Defaults to ``"bhived"``.
        api_key: bhived API key. Defaults to ``BHIVED_API_KEY`` or the key
            saved by ``npx bhived setup``.
        api_url: API base URL. Defaults to ``BHIVED_API_URL`` or
            ``https://mcp.bhived.ai``.
        client: A ready-made :class:`bhived.BhivedClient`.
        async_client: A ready-made :class:`bhived.AsyncBhivedClient` (the one
            the provider uses).
        clients: A :class:`BhivedClients` to share with :func:`bhived_tools`.
        top_k: How many results to ask for per tier (1-100).
        scope: ``team_plus_global`` (server default), ``team_only`` or
            ``global_only``.
        max_tokens: Rough upper bound for the added block, counted as about
            four characters per token.
        context: Optional fixed context sent with every query, such as
            ``"Python 3.12, Azure Functions"``.
        include_warnings: Also add known mistakes (recommended).
        min_query_chars: Skip recall for shorter user messages ("thanks", "ok").
        max_query_chars: Only the first this-many characters of the user
            message are sent as the query.
        cache_size: How many recent queries to remember. 0 disables the cache.
        cache_ttl: Seconds a cached result stays valid.
        build_query: Optional function that turns the run's ``SessionContext``
            into the query text. Return None to skip recall for that run.
        raise_on_error: By default a failed recall is logged and the run goes
            ahead without lessons. Set True to raise instead.
    """

    def __init__(
        self,
        source_id: str = DEFAULT_SOURCE_ID,
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
        build_query: Optional[Callable[[SessionContext], Optional[str]]] = None,
        raise_on_error: bool = False,
    ) -> None:
        if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 100:
            raise ValueError("top_k must be an integer from 1 to 100")
        if scope is not None and scope not in SCOPES:
            raise ValueError(f"scope must be one of {', '.join(SCOPES)}")
        if max_tokens < MIN_MAX_TOKENS:
            raise ValueError(f"max_tokens must be at least {MIN_MAX_TOKENS}")
        super().__init__(source_id)
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
        self.build_query = build_query
        self.raise_on_error = raise_on_error
        self._cache = RecallCache(cache_size, cache_ttl)
        self._failures = FailureLog(logger)

    async def before_run(
        self,
        *,
        agent: Any,
        session: AgentSession,
        context: SessionContext,
        state: dict[str, Any],
    ) -> None:
        text = self.build_query(context) if self.build_query else latest_user_text(context.input_messages)
        query = clean_query(text, min_chars=self.min_query_chars, max_chars=self.max_query_chars)
        if query is None:
            return
        result = self._cache.get(query)
        if result is None:
            try:
                result = await self.clients.async_.query(
                    query,
                    context=self.context,
                    top_k=self.top_k,
                    scope=self.scope,  # type: ignore[arg-type]
                    include_warnings=self.include_warnings,
                    include_episodes=False,
                    include_disputed=False,
                )
            except BhivedError as exc:
                if self.raise_on_error:
                    raise
                self._failures.report(exc)
                return
            self._cache.put(query, result)
        block = result.as_context(
            max_tokens=self.max_tokens,
            include_warnings=self.include_warnings,
            mention_write_tools=bool(_agent_tool_names(agent, context) & set(WRITE_TOOL_NAMES)),
        )
        if block:
            context.extend_instructions(self.source_id, block)
