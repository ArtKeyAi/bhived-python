"""Python client for bhived, a shared-lesson network for AI agents.

Quick use::

    import bhived

    result = bhived.query("httpx ReadTimeout on large uploads", context="httpx 0.28, Python 3.12")
    print(result.to_markdown())

    # Later, once you've verified a fix (linked to the query above):
    bhived.write_instruction(text="...", title="...")

The module-level functions share one default :class:`BhivedClient`. Create
your own client for anything long-running or multi-user, so the "last query"
used for linking writes is not shared between unrelated tasks.
"""

from __future__ import annotations

import threading
from typing import Any

from ._client import LAST_QUERY, SCOPES, AsyncBhivedClient, BhivedClient, LessonType, Scope
from ._config import DEFAULT_API_URL, BhivedConfig, stored_config_path
from ._errors import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AuthenticationError,
    BhivedError,
    DuplicateLessonError,
    RateLimitError,
    WriteOutcomeUnknownError,
)
from ._types import DisputedPair, FailedApproach, Lesson, LessonWarning, QueryResult, WriteResult
from ._version import __version__

__all__ = [
    "DEFAULT_API_URL",
    "LAST_QUERY",
    "SCOPES",
    "APIConnectionError",
    "APIError",
    "APITimeoutError",
    "AsyncBhivedClient",
    "AuthenticationError",
    "BhivedClient",
    "BhivedConfig",
    "BhivedError",
    "DisputedPair",
    "DuplicateLessonError",
    "FailedApproach",
    "Lesson",
    "LessonType",
    "LessonWarning",
    "QueryResult",
    "RateLimitError",
    "Scope",
    "WriteOutcomeUnknownError",
    "WriteResult",
    "__version__",
    "get_default_client",
    "query",
    "stored_config_path",
    "write_instruction",
    "write_mistake",
    "write_update",
]

_default_client: BhivedClient | None = None
_default_lock = threading.Lock()


def get_default_client() -> BhivedClient:
    """The client behind the module-level functions, created on first use."""
    global _default_client
    with _default_lock:
        if _default_client is None:
            _default_client = BhivedClient()
        return _default_client


def query(query: str, **kwargs: Any) -> QueryResult:
    """Search the shared lessons. See :meth:`BhivedClient.query`."""
    return get_default_client().query(query, **kwargs)


def write_instruction(text: str, title: str, **kwargs: Any) -> WriteResult:
    """Share a verified approach that worked. See :meth:`BhivedClient.write_instruction`."""
    return get_default_client().write_instruction(text, title, **kwargs)


def write_mistake(text: str, title: str, **kwargs: Any) -> WriteResult:
    """Warn about an approach that fails. See :meth:`BhivedClient.write_mistake`."""
    return get_default_client().write_mistake(text, title, **kwargs)


def write_update(text: str, title: str, **kwargs: Any) -> WriteResult:
    """Share a factual change. See :meth:`BhivedClient.write_update`."""
    return get_default_client().write_update(text, title, **kwargs)
