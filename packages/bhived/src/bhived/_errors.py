"""Errors raised by the bhived client. None of them ever carry the API key."""

from __future__ import annotations

import json
from typing import Any, Literal

_MAX_BODY_IN_MESSAGE = 500


def api_error_code(body: str | None) -> str | None:
    """The ``error`` code of an error body.

    Accepts ``{"detail": {"error": code}}`` (FastAPI), ``{"error": code}`` and
    ``{"detail": "code"}``. None when the body has no code.
    """
    parsed = _parse_body(body)
    if parsed is None:
        return None
    detail = parsed.get("detail")
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict) and isinstance(detail.get("error"), str):
        return detail["error"]
    error = parsed.get("error")
    return error if isinstance(error, str) else None


def _parse_body(body: str | None) -> dict[str, Any] | None:
    if not body:
        return None
    try:
        parsed = json.loads(body)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _error_detail(body: str | None) -> dict[str, Any]:
    """The error object itself: ``detail`` when FastAPI wrapped it, else the body."""
    parsed = _parse_body(body) or {}
    detail = parsed.get("detail")
    return detail if isinstance(detail, dict) else parsed


class BhivedError(Exception):
    """Base class for every error this package raises."""


class APIError(BhivedError):
    """The API answered with an error status."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        body: str = "",
        retry_after: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body
        self.retry_after = retry_after

    @property
    def code(self) -> str | None:
        """The ``error`` code from the response body, if there is one."""
        return api_error_code(self.body)

    @classmethod
    def from_response(cls, status_code: int, body: str, reason: str, retry_after: str | None) -> APIError:
        shown = body if len(body) <= _MAX_BODY_IN_MESSAGE else body[:_MAX_BODY_IN_MESSAGE] + "..."
        message = f"bhived API error ({status_code}): {shown or reason}"
        kwargs: dict[str, Any] = {"status_code": status_code, "body": body, "retry_after": retry_after}
        if status_code in (401, 403):
            return AuthenticationError(
                message + ". Check your key: run `npx bhived setup` or set BHIVED_API_KEY.", **kwargs
            )
        if status_code == 429:
            return RateLimitError(message, **kwargs)
        if status_code == 409 and api_error_code(body) == "duplicate_memory":
            return DuplicateLessonError(message, **kwargs)
        return cls(message, **kwargs)


class AuthenticationError(APIError):
    """No API key is configured, or the API rejected the key (401/403)."""


class RateLimitError(APIError):
    """Too many requests for this key (429). Not retried automatically."""


class DuplicateLessonError(APIError):
    """The write was rejected because a near-identical lesson already exists."""

    @property
    def duplicate_of(self) -> str | None:
        detail = _error_detail(self.body)
        for name in ("duplicate_of", "duplicateOf", "existing_id", "memory_id"):
            if isinstance(detail.get(name), str):
                return detail[name]
        return None

    @property
    def similarity(self) -> float | None:
        detail = _error_detail(self.body)
        for name in ("jaccard_similarity", "similarity", "score"):
            value = detail.get(name)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
        return None


class APIConnectionError(BhivedError):
    """The API could not be reached."""


class APITimeoutError(APIConnectionError):
    """A request took longer than the configured timeout."""


class WriteOutcomeUnknownError(BhivedError):
    """A write whose result the client cannot know.

    It timed out, lost the connection, kept failing with a 5xx, or was still
    running on the server when the write deadline passed. The lesson may have
    been saved. Calling the same write again with identical arguments on the
    same client is safe: it reuses the idempotency key, so the lesson is saved
    at most once.
    """

    def __init__(self, message: str, reason: Literal["timeout", "network", "server_error", "in_progress"]) -> None:
        super().__init__(message)
        self.reason = reason
