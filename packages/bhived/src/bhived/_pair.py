from __future__ import annotations

import threading
from typing import Optional

from ._client import AsyncBhivedClient, BhivedClient
from ._config import BhivedConfig


class BhivedClients:
    """A sync and an async client that share one config, each created on first use.

    Frameworks may call an adapter either way (``invoke`` or ``ainvoke``), so
    adapters hold one of these instead of a single client.
    """

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        api_url: Optional[str] = None,
        client: Optional[BhivedClient] = None,
        async_client: Optional[AsyncBhivedClient] = None,
        user_agent: Optional[str] = None,
    ) -> None:
        if client is not None:
            self.config = client.config
        elif async_client is not None:
            self.config = async_client.config
        else:
            self.config = BhivedConfig.resolve(api_key=api_key, api_url=api_url)
        self._sync = client
        self._async = async_client
        self._user_agent = user_agent
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return f"BhivedClients({self.config!r})"

    @property
    def sync(self) -> BhivedClient:
        with self._lock:
            if self._sync is None:
                self._sync = BhivedClient(config=self.config, user_agent=self._user_agent)
            return self._sync

    @property
    def async_(self) -> AsyncBhivedClient:
        with self._lock:
            if self._async is None:
                self._async = AsyncBhivedClient(config=self.config, user_agent=self._user_agent)
            return self._async
