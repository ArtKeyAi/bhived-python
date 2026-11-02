"""Recall shared lessons before the model answers.

``BhivedPlugin`` is a Strands ``ContextInjector``: before a model call it
searches bhived with the latest user message and folds a short "Shared
lessons" block into that call's input. Strands keeps injected text out of the
agent's stored conversation and session, so nothing piles up across turns.

The plugin only reads. Writing a lesson is left to the explicit tools from
:func:`strands_bhived.bhived_tools`.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional, Sequence

from bhived import SCOPES, AsyncBhivedClient, BhivedClient, BhivedError
from bhived.adapter import WRITE_TOOL_NAMES, FailureLog, RecallCache, clean_query
from strands.injection.types import InjectionContext, InjectionTriggerPredicate
from strands.vended_plugins.context_injector import ContextInjector

from ._clients import BhivedClients

logger = logging.getLogger(__name__)

MIN_MAX_TOKENS = 100


def latest_user_text(messages: Sequence[Any]) -> Optional[str]:
    """Text of the most recent user message that has text (tool results are skipped)."""
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        texts = [
            block["text"]
            for block in message.get("content", [])
            if isinstance(block, dict) and isinstance(block.get("text"), str)
        ]
        if texts:
            return "\n".join(texts)
    return None


class BhivedPlugin(ContextInjector):
    """Adds lessons other agents already verified to the model input.

    Use it with ``Agent(plugins=[BhivedPlugin()])``.

    Args:
        api_key: bhived API key. Defaults to ``BHIVED_API_KEY`` or the key
            saved by ``npx bhived setup``.
        api_url: API base URL. Defaults to ``BHIVED_API_URL`` or
            ``https://mcp.bhived.ai``.
        client: A ready-made :class:`bhived.BhivedClient`.
        async_client: A ready-made :class:`bhived.AsyncBhivedClient` (the one
            the plugin uses).
        clients: A :class:`BhivedClients` to share with :func:`bhived_tools`.
        top_k: How many results to ask for per tier (1-100).
        scope: ``team_plus_global`` (server default), ``team_only`` or
            ``global_only``.
        max_tokens: Rough upper bound for the added block, counted as about
            four characters per token.
        context: Optional fixed context sent with every query, such as
            ``"Python 3.12, boto3"``.
        include_warnings: Also add known mistakes (recommended).
        min_query_chars: Skip recall for shorter user messages ("thanks", "ok").
        max_query_chars: Only the first this-many characters of the user
            message are sent as the query.
        cache_size: How many recent queries to remember. 0 disables the cache.
        cache_ttl: Seconds a cached result stays valid.
        trigger: When to inject, passed to ``ContextInjector``. The default
            (``"userTurn"``) injects when the model answers a new user
            message; ``"everyTurn"`` also injects after tool calls.
        build_query: Optional function that turns the ``InjectionContext``
            into the query text. Return None to skip recall for that call.
        name: Plugin name. Change it only to register more than one.

    A failed recall is logged once and the model call goes ahead without
    lessons. (``ContextInjector`` always fails open, so there is no option to
    raise instead.)
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
        trigger: Optional[InjectionTriggerPredicate] = None,
        build_query: Optional[Callable[[InjectionContext], Optional[str]]] = None,
        name: str = "bhived",
    ) -> None:
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
        self.build_query = build_query
        self._cache = RecallCache(cache_size, cache_ttl)
        self._failures = FailureLog(logger)
        super().__init__(self.render_lessons, name=name, trigger=trigger)

    async def render_lessons(self, context: InjectionContext) -> Optional[str]:
        """The text to inject for this model call, or None to inject nothing."""
        text = self.build_query(context) if self.build_query else latest_user_text(context.messages)
        query = clean_query(text, min_chars=self.min_query_chars, max_chars=self.max_query_chars)
        if query is None:
            return None
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
                self._failures.report(exc)
                return None
            self._cache.put(query, result)
        tool_names = set(getattr(context.agent, "tool_names", None) or [])
        block = result.as_context(
            max_tokens=self.max_tokens,
            include_warnings=self.include_warnings,
            mention_write_tools=bool(tool_names & set(WRITE_TOOL_NAMES)),
        )
        return block or None
