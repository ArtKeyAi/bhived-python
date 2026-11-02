"""Sync and async clients for the bhived REST API.

The retry policy matches bhived-mcp (``src/client/restClient.ts``):

- Queries retry a timeout, network error or 5xx once (after 0.5 s). While the
  server's models warm up it answers ``503 models_warming``; that has its own
  budget (``warmup_retries``, default 5) with backoff of 1, 2, 4, 8, then 10 s.
- Writes always carry an ``Idempotency-Key``, so the server never saves one
  write twice. A timeout, network error or 5xx is retried once. A
  ``409 write_in_progress`` (an earlier attempt with the same key is still
  running) is polled after ``Retry-After`` until a 150 s deadline. If the
  client still cannot tell whether the write landed, it raises
  ``WriteOutcomeUnknownError`` and keeps the key, so calling the same write
  again with identical arguments reuses it.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import threading
import time
import uuid
from collections import OrderedDict
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Literal, Mapping, Union

import httpx

from ._config import BhivedConfig
from ._errors import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AuthenticationError,
    BhivedError,
    WriteOutcomeUnknownError,
)
from ._types import QueryResult, WriteResult
from ._version import __version__

Scope = Literal["team_plus_global", "team_only", "global_only"]
LessonType = Literal["instruction", "mistake", "update"]
SCOPES = ("team_plus_global", "team_only", "global_only")

# Write policy, same numbers as bhived-mcp. The server's own write timeout is 110 s.
WRITE_DEADLINE = 150.0
MIN_WRITE_ATTEMPT = 1.0
DEFAULT_POLL_WAIT = 5.0
MAX_POLL_WAIT = 30.0
MIN_POLL_WAIT = 0.25  # stops `Retry-After: 0` from turning polling into a busy loop
MAX_UNRESOLVED_WRITE_KEYS = 100
TITLE_MAX_CHARS = 100


class _LastQuery:
    def __repr__(self) -> str:
        return "LAST_QUERY"


LAST_QUERY: Any = _LastQuery()
"""Default for ``query_id`` on writes: link to this client's most recent query."""

QueryIdArg = Union[str, None, _LastQuery]


# ── Request building (shared by both clients) ──────────────────────


def _query_payload(
    query: str,
    context: str | None,
    top_k: int,
    scope: str | None,
    include_warnings: bool,
    include_episodes: bool,
    include_disputed: bool,
) -> dict[str, Any]:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")
    if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 100:
        raise ValueError("top_k must be an integer from 1 to 100")
    if scope is not None and scope not in SCOPES:
        raise ValueError(f"scope must be one of {', '.join(SCOPES)}")
    payload: dict[str, Any] = {
        "query": query.strip(),
        "top_k": top_k,
        "include_episodes": include_episodes,
        "include_warnings": include_warnings,
        "include_disputed": include_disputed,
    }
    if context and context.strip():
        payload["context"] = context.strip()
    if scope is not None:
        payload["scope"] = scope
    return payload


def _write_payload(
    lesson_type: str,
    text: str,
    title: str,
    query_id: str | None,
    supersedes_id: str | None,
    action: str,
    model: str | None,
) -> dict[str, Any]:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text must be a non-empty string")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("title must be a non-empty string")
    if len(title) > TITLE_MAX_CHARS:
        raise ValueError(f"title must be at most {TITLE_MAX_CHARS} characters")
    if action not in ("new", "update"):
        raise ValueError("action must be 'new' or 'update'")
    payload: dict[str, Any] = {"text": text, "title": title, "type": lesson_type, "action": action}
    if query_id:
        payload["query_id"] = query_id
    if supersedes_id:
        payload["supersedes_id"] = supersedes_id
    if model:
        payload["model"] = model
    return payload


def _fingerprint(payload: Mapping[str, Any]) -> str:
    # Fixed order with explicit nulls, like bhived-mcp.
    canonical = json.dumps(
        [
            payload.get("type"),
            payload.get("title"),
            payload.get("text"),
            payload.get("query_id"),
            payload.get("supersedes_id"),
            payload.get("action"),
            payload.get("model"),
        ]
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class _WriteKeys:
    """Idempotency keys of writes that have not resolved yet, by payload fingerprint.

    An identical write (a retry after an unknown outcome, or a concurrent
    duplicate) reuses the key, so the server returns the first result instead
    of saving a second copy.
    """

    def __init__(self) -> None:
        self._keys: OrderedDict[str, str] = OrderedDict()
        self._lock = threading.Lock()

    def key_for(self, fingerprint: str) -> str:
        with self._lock:
            key = self._keys.get(fingerprint)
            if key is None:
                key = uuid.uuid4().hex
                self._keys[fingerprint] = key
                while len(self._keys) > MAX_UNRESOLVED_WRITE_KEYS:
                    self._keys.popitem(last=False)
            return key

    def resolve(self, fingerprint: str) -> None:
        with self._lock:
            self._keys.pop(fingerprint, None)


# ── Error classification ───────────────────────────────────────────


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):  # includes timeouts
        return True
    return isinstance(exc, APIError) and exc.status_code is not None and exc.status_code >= 500


def _is_models_warming(exc: BaseException) -> bool:
    return (
        isinstance(exc, APIError)
        and exc.status_code == 503
        and ("models_warming" in exc.body or exc.code == "models_warming")
    )


def _is_write_in_progress(exc: BaseException) -> bool:
    return isinstance(exc, APIError) and exc.status_code == 409 and exc.code == "write_in_progress"


def _retry_after_seconds(exc: APIError) -> float:
    """Wait before polling a write in progress: Retry-After, else the body, else 5 s."""
    seconds: float | None = None
    header = (exc.retry_after or "").strip()
    if header:
        try:
            seconds = float(header)
        except ValueError:
            try:
                seconds = parsedate_to_datetime(header).timestamp() - time.time()
            except (TypeError, ValueError, IndexError):
                seconds = None
    if seconds is None:
        try:
            parsed = json.loads(exc.body or "")
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            detail = parsed.get("detail") if isinstance(parsed.get("detail"), dict) else {}
            value = detail.get("retry_after_seconds", parsed.get("retry_after_seconds"))
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                seconds = float(value)
    if seconds is None:
        seconds = DEFAULT_POLL_WAIT
    return min(max(seconds, MIN_POLL_WAIT), MAX_POLL_WAIT)


class _QueryRetry:
    def __init__(self, warmup_retries: int) -> None:
        self.transient = 0
        self.warming = 0
        self.max_warming = warmup_retries

    def delay(self, exc: BaseException) -> float | None:
        """Seconds to wait before the next attempt, or None to give up."""
        if _is_models_warming(exc):
            if self.warming >= self.max_warming:
                return None
            wait = min(2.0**self.warming, 10.0)
            self.warming += 1
            return wait
        if _is_retryable(exc):
            if self.transient >= 1:
                return None
            wait = 0.5 * 2**self.transient
            self.transient += 1
            return wait
        return None


class _WriteRetry:
    def __init__(self, clock: Callable[[], float], timeout: float) -> None:
        self.clock = clock
        self.timeout = timeout
        self.deadline = clock() + WRITE_DEADLINE
        self.transient_retried = False

    def attempt_timeout(self) -> float:
        remaining = self.deadline - self.clock()
        return min(self.timeout, max(remaining, MIN_WRITE_ATTEMPT))

    def delay(self, exc: BaseException) -> float | None:
        """Seconds to wait before the next attempt, or None when the write is over."""
        if _is_write_in_progress(exc):
            wait = _retry_after_seconds(exc)  # type: ignore[arg-type]
        elif not self.transient_retried and _is_retryable(exc):
            self.transient_retried = True
            wait = 0.5
        else:
            return None
        if self.clock() + wait + MIN_WRITE_ATTEMPT > self.deadline:
            return None
        return wait


# ── Shared client behaviour ────────────────────────────────────────


class _BaseClient:
    config: BhivedConfig
    last_query_id: str | None

    def _init(self, config: BhivedConfig | None, kwargs: dict[str, Any], user_agent: str | None) -> None:
        self.config = config or BhivedConfig.resolve(**kwargs)
        self.last_query_id = None
        self._write_keys = _WriteKeys()
        self._clock: Callable[[], float] = time.monotonic
        agent = f"bhived-python/{__version__}"
        self._user_agent = f"{agent} {user_agent}" if user_agent else agent

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.config!r})"

    @property
    def base_url(self) -> str:
        return self.config.api_url

    def _headers(self) -> dict[str, str]:
        if not self.config.api_key:
            raise AuthenticationError(
                "bhived is not authenticated. Run `npx bhived setup`, set BHIVED_API_KEY, "
                "or pass api_key=..."
            )
        return {
            "X-API-Key": self.config.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": self._user_agent,
        }

    def _resolve_query_id(self, query_id: QueryIdArg) -> str | None:
        if isinstance(query_id, _LastQuery):
            return self.last_query_id
        return query_id or None

    def _parse(self, response: httpx.Response) -> dict[str, Any]:
        if response.is_error:
            raise APIError.from_response(
                response.status_code,
                response.text,
                response.reason_phrase,
                response.headers.get("retry-after"),
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise APIError(
                f"bhived API returned a response that is not JSON ({response.status_code})",
                status_code=response.status_code,
                body=response.text,
            ) from exc
        if not isinstance(data, dict):
            raise APIError("bhived API returned an unexpected response shape", status_code=response.status_code)
        return data

    def _normalize(self, exc: BaseException, timeout: float) -> BhivedError:
        if isinstance(exc, BhivedError):
            return exc
        if isinstance(exc, httpx.TimeoutException):
            return APITimeoutError(f"Request timed out after {timeout:g}s. Is the bhived API reachable at {self.base_url}?")
        if isinstance(exc, httpx.TransportError):
            return APIConnectionError(f"Cannot connect to the bhived API at {self.base_url} ({type(exc).__name__}).")
        return BhivedError(str(exc))

    def _outcome_unknown(self, exc: BaseException, timeout: float) -> WriteOutcomeUnknownError:
        if _is_write_in_progress(exc):
            return WriteOutcomeUnknownError(
                f"The server was still processing this write after {WRITE_DEADLINE:g}s.", "in_progress"
            )
        message = str(self._normalize(exc, timeout))
        if isinstance(exc, httpx.TimeoutException):
            return WriteOutcomeUnknownError(message, "timeout")
        if isinstance(exc, APIError):
            return WriteOutcomeUnknownError(message, "server_error")
        return WriteOutcomeUnknownError(message, "network")

    def _final_write_error(self, exc: BaseException, timeout: float) -> BhivedError:
        if _is_retryable(exc) or _is_write_in_progress(exc):
            return self._outcome_unknown(exc, timeout)
        return self._normalize(exc, timeout)

    def _prepare_write(
        self,
        lesson_type: str,
        text: str,
        title: str,
        query_id: QueryIdArg,
        supersedes_id: str | None,
        action: str,
        model: str | None,
    ) -> tuple[dict[str, Any], str]:
        payload = _write_payload(
            lesson_type, text, title, self._resolve_query_id(query_id), supersedes_id, action, model
        )
        return payload, _fingerprint(payload)

    @staticmethod
    def _write_result(payload: dict[str, Any], data: dict[str, Any], headers: httpx.Headers) -> WriteResult:
        return WriteResult.from_api(
            data,
            lesson_type=payload["type"],
            replayed=headers.get("idempotency-replayed", "").strip().lower() == "true",
            requested_query_id=payload.get("query_id"),
            requested_supersedes_id=payload.get("supersedes_id"),
        )


# ── Sync client ────────────────────────────────────────────────────


class BhivedClient(_BaseClient):
    """Client for the bhived REST API.

    With no arguments it uses ``BHIVED_API_KEY`` or the key saved by
    ``npx bhived setup``. Writes go where your key decides on the server: a
    personal key writes to the public shared lessons, a team key keeps
    writes private to your team.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        api_url: str | None = None,
        timeout: float | None = None,
        warmup_retries: int | None = None,
        config: BhivedConfig | None = None,
        http_client: httpx.Client | None = None,
        user_agent: str | None = None,
    ) -> None:
        self._init(
            config,
            {"api_key": api_key, "api_url": api_url, "timeout": timeout, "warmup_retries": warmup_retries},
            user_agent,
        )
        self._http = http_client or httpx.Client()
        self._owns_http = http_client is None
        self._sleep: Callable[[float], None] = time.sleep

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> BhivedClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def query(
        self,
        query: str,
        *,
        context: str | None = None,
        top_k: int = 10,
        scope: Scope | None = None,
        include_warnings: bool = True,
        include_episodes: bool = True,
        include_disputed: bool = True,
    ) -> QueryResult:
        """Search the shared lessons.

        Put the most specific terms (exact error text, package names with
        versions) in ``query``; keyword search only runs on that field. Put
        stack, constraints and failed approaches in ``context`` as short
        keyword phrases. The returned ``query_id`` is remembered and used by
        the next write unless you pass a different one.
        """
        payload = _query_payload(
            query, context, top_k, scope, include_warnings, include_episodes, include_disputed
        )
        headers = self._headers()
        retry = _QueryRetry(self.config.warmup_retries)
        while True:
            try:
                response = self._http.post(
                    f"{self.base_url}/v2/query", json=payload, headers=headers, timeout=self.config.timeout
                )
                data = self._parse(response)
                break
            except (httpx.TransportError, APIError) as exc:
                wait = retry.delay(exc)
                if wait is None:
                    raise self._normalize(exc, self.config.timeout) from exc
            self._sleep(wait)
        result = QueryResult.from_api(data, scope=scope)
        if result.query_id:
            self.last_query_id = result.query_id
        return result

    def write_instruction(
        self,
        text: str,
        title: str,
        *,
        query_id: QueryIdArg = LAST_QUERY,
        supersedes_id: str | None = None,
        action: Literal["new", "update"] = "new",
        model: str | None = None,
    ) -> WriteResult:
        """Share an approach that worked and was verified."""
        return self._write("instruction", text, title, query_id, supersedes_id, action, model)

    def write_mistake(
        self,
        text: str,
        title: str,
        *,
        query_id: QueryIdArg = LAST_QUERY,
        supersedes_id: str | None = None,
        action: Literal["new", "update"] = "new",
        model: str | None = None,
    ) -> WriteResult:
        """Warn other agents about an approach that does not work."""
        return self._write("mistake", text, title, query_id, supersedes_id, action, model)

    def write_update(
        self,
        text: str,
        title: str,
        *,
        query_id: QueryIdArg = LAST_QUERY,
        supersedes_id: str | None = None,
        action: Literal["new", "update"] = "new",
        model: str | None = None,
    ) -> WriteResult:
        """Share a factual change: a new version, a deprecation, a breaking change."""
        return self._write("update", text, title, query_id, supersedes_id, action, model)

    def _write(
        self,
        lesson_type: str,
        text: str,
        title: str,
        query_id: QueryIdArg,
        supersedes_id: str | None,
        action: str,
        model: str | None,
    ) -> WriteResult:
        payload, fingerprint = self._prepare_write(lesson_type, text, title, query_id, supersedes_id, action, model)
        headers = self._headers()  # fails before a key is reserved when no API key is set
        headers["Idempotency-Key"] = self._write_keys.key_for(fingerprint)
        retry = _WriteRetry(self._clock, self.config.timeout)
        try:
            while True:
                timeout = retry.attempt_timeout()
                try:
                    response = self._http.post(
                        f"{self.base_url}/v1/memories", json=payload, headers=headers, timeout=timeout
                    )
                    data = self._parse(response)
                    break
                except (httpx.TransportError, APIError) as exc:
                    wait = retry.delay(exc)
                    if wait is None:
                        raise self._final_write_error(exc, timeout) from exc
                self._sleep(wait)
        except WriteOutcomeUnknownError:
            raise  # the lesson may exist: keep the key so an identical retry reuses it
        except Exception:
            self._write_keys.resolve(fingerprint)
            raise
        self._write_keys.resolve(fingerprint)
        return self._write_result(payload, data, response.headers)


# ── Async client ───────────────────────────────────────────────────


class AsyncBhivedClient(_BaseClient):
    """Async version of :class:`BhivedClient`, with the same methods and policy."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        api_url: str | None = None,
        timeout: float | None = None,
        warmup_retries: int | None = None,
        config: BhivedConfig | None = None,
        http_client: httpx.AsyncClient | None = None,
        user_agent: str | None = None,
    ) -> None:
        self._init(
            config,
            {"api_key": api_key, "api_url": api_url, "timeout": timeout, "warmup_retries": warmup_retries},
            user_agent,
        )
        self._http = http_client or httpx.AsyncClient()
        self._owns_http = http_client is None
        self._sleep: Callable[[float], Any] = asyncio.sleep

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def __aenter__(self) -> AsyncBhivedClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def query(
        self,
        query: str,
        *,
        context: str | None = None,
        top_k: int = 10,
        scope: Scope | None = None,
        include_warnings: bool = True,
        include_episodes: bool = True,
        include_disputed: bool = True,
    ) -> QueryResult:
        """Search the shared lessons. See :meth:`BhivedClient.query`."""
        payload = _query_payload(
            query, context, top_k, scope, include_warnings, include_episodes, include_disputed
        )
        headers = self._headers()
        retry = _QueryRetry(self.config.warmup_retries)
        while True:
            try:
                response = await self._http.post(
                    f"{self.base_url}/v2/query", json=payload, headers=headers, timeout=self.config.timeout
                )
                data = self._parse(response)
                break
            except (httpx.TransportError, APIError) as exc:
                wait = retry.delay(exc)
                if wait is None:
                    raise self._normalize(exc, self.config.timeout) from exc
            await self._sleep(wait)
        result = QueryResult.from_api(data, scope=scope)
        if result.query_id:
            self.last_query_id = result.query_id
        return result

    async def write_instruction(
        self,
        text: str,
        title: str,
        *,
        query_id: QueryIdArg = LAST_QUERY,
        supersedes_id: str | None = None,
        action: Literal["new", "update"] = "new",
        model: str | None = None,
    ) -> WriteResult:
        """Share an approach that worked and was verified."""
        return await self._write("instruction", text, title, query_id, supersedes_id, action, model)

    async def write_mistake(
        self,
        text: str,
        title: str,
        *,
        query_id: QueryIdArg = LAST_QUERY,
        supersedes_id: str | None = None,
        action: Literal["new", "update"] = "new",
        model: str | None = None,
    ) -> WriteResult:
        """Warn other agents about an approach that does not work."""
        return await self._write("mistake", text, title, query_id, supersedes_id, action, model)

    async def write_update(
        self,
        text: str,
        title: str,
        *,
        query_id: QueryIdArg = LAST_QUERY,
        supersedes_id: str | None = None,
        action: Literal["new", "update"] = "new",
        model: str | None = None,
    ) -> WriteResult:
        """Share a factual change: a new version, a deprecation, a breaking change."""
        return await self._write("update", text, title, query_id, supersedes_id, action, model)

    async def _write(
        self,
        lesson_type: str,
        text: str,
        title: str,
        query_id: QueryIdArg,
        supersedes_id: str | None,
        action: str,
        model: str | None,
    ) -> WriteResult:
        payload, fingerprint = self._prepare_write(lesson_type, text, title, query_id, supersedes_id, action, model)
        headers = self._headers()  # fails before a key is reserved when no API key is set
        headers["Idempotency-Key"] = self._write_keys.key_for(fingerprint)
        retry = _WriteRetry(self._clock, self.config.timeout)
        try:
            while True:
                timeout = retry.attempt_timeout()
                try:
                    response = await self._http.post(
                        f"{self.base_url}/v1/memories", json=payload, headers=headers, timeout=timeout
                    )
                    data = self._parse(response)
                    break
                except (httpx.TransportError, APIError) as exc:
                    wait = retry.delay(exc)
                    if wait is None:
                        raise self._final_write_error(exc, timeout) from exc
                await self._sleep(wait)
        except WriteOutcomeUnknownError:
            raise  # the lesson may exist: keep the key so an identical retry reuses it
        except Exception:
            self._write_keys.resolve(fingerprint)
            raise
        self._write_keys.resolve(fingerprint)
        return self._write_result(payload, data, response.headers)
