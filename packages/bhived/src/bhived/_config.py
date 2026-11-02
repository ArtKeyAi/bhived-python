"""Where the client finds its API key and base URL.

The lookup order is the same as bhived-mcp, so one `npx bhived setup` works
for both:

- key: the explicit argument, then ``BHIVED_API_KEY``, then ``apiKey`` in
  ``~/.bhived/config.json``
- URL: the explicit argument, then ``BHIVED_API_URL``, then ``apiUrl`` in
  ``~/.bhived/config.json``, then ``https://mcp.bhived.ai``

The key is never printed: ``repr()`` masks it.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_API_URL = "https://mcp.bhived.ai"
DEFAULT_TIMEOUT = 30.0
DEFAULT_WARMUP_RETRIES = 5


def stored_config_path() -> Path:
    """Path of the credential file written by ``npx bhived setup``."""
    return Path.home() / ".bhived" / "config.json"


def read_stored_config(path: Path | None = None) -> dict[str, Any]:
    """Read ``~/.bhived/config.json``. Empty when missing, unreadable or keyless."""
    try:
        data = json.loads((path or stored_config_path()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or not data.get("apiKey"):
        return {}
    return data


def _clean(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _env_timeout() -> float | None:
    # BHIVED_TIMEOUT is in milliseconds, as in bhived-mcp.
    raw = _clean(os.environ.get("BHIVED_TIMEOUT"))
    if raw is None:
        return None
    try:
        ms = float(raw)
    except ValueError:
        return None
    return ms / 1000 if ms > 0 else None


def _env_warmup_retries() -> int | None:
    # A non-numeric value must not break the retry loop, so fall back.
    raw = _clean(os.environ.get("BHIVED_WARMUP_RETRIES"))
    if raw is None:
        return None
    try:
        n = int(raw)
    except ValueError:
        return None
    return n if n >= 0 else None


@dataclass(frozen=True)
class BhivedConfig:
    """Connection settings for one API key."""

    api_key: str | None = field(default=None, repr=False)
    api_url: str = DEFAULT_API_URL
    timeout: float = DEFAULT_TIMEOUT
    """Seconds per request attempt."""
    warmup_retries: int = DEFAULT_WARMUP_RETRIES
    """How many times a query is retried while the server's models warm up."""

    def __post_init__(self) -> None:
        object.__setattr__(self, "api_url", self.api_url.rstrip("/"))

    def __repr__(self) -> str:
        key = "'***'" if self.api_key else "None"
        return (
            f"BhivedConfig(api_key={key}, api_url={self.api_url!r}, "
            f"timeout={self.timeout!r}, warmup_retries={self.warmup_retries!r})"
        )

    @classmethod
    def resolve(
        cls,
        *,
        api_key: str | None = None,
        api_url: str | None = None,
        timeout: float | None = None,
        warmup_retries: int | None = None,
    ) -> BhivedConfig:
        """Build a config from arguments, then the environment, then the stored file."""
        stored = read_stored_config()
        if timeout is None:
            timeout = _env_timeout() or DEFAULT_TIMEOUT
        if warmup_retries is None:
            warmup_retries = _env_warmup_retries()
        if warmup_retries is None:
            warmup_retries = DEFAULT_WARMUP_RETRIES
        return cls(
            api_key=_clean(api_key)
            or _clean(os.environ.get("BHIVED_API_KEY"))
            or _clean(stored.get("apiKey")),
            api_url=_clean(api_url)
            or _clean(os.environ.get("BHIVED_API_URL"))
            or _clean(stored.get("apiUrl"))
            or DEFAULT_API_URL,
            timeout=timeout,
            warmup_retries=warmup_retries,
        )
