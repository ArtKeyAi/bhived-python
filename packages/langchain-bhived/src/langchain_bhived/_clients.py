from __future__ import annotations

import threading

from bhived import AsyncBhivedClient, BhivedClient, BhivedConfig

from ._version import __version__

USER_AGENT = f"langchain-bhived/{__version__}"


class BhivedClients:
    """A sync and an async bhived client that share one config.

    LangChain may call the middleware and tools either way (``invoke`` or
    ``ainvoke``), so both are needed. Each is created on first use.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_url: str | None = None,
        client: BhivedClient | None = None,
        async_client: AsyncBhivedClient | None = None,
    ) -> None:
        if client is not None:
            self.config = client.config
        elif async_client is not None:
            self.config = async_client.config
        else:
            self.config = BhivedConfig.resolve(api_key=api_key, api_url=api_url)
        self._sync = client
        self._async = async_client
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return f"BhivedClients({self.config!r})"

    @property
    def sync(self) -> BhivedClient:
        with self._lock:
            if self._sync is None:
                self._sync = BhivedClient(config=self.config, user_agent=USER_AGENT)
            return self._sync

    @property
    def async_(self) -> AsyncBhivedClient:
        with self._lock:
            if self._async is None:
                self._async = AsyncBhivedClient(config=self.config, user_agent=USER_AGENT)
            return self._async
