from __future__ import annotations

from typing import Any

from bhived import BhivedClients as _CoreClients

from ._version import __version__

USER_AGENT = f"langchain-bhived/{__version__}"


class BhivedClients(_CoreClients):
    """A sync and an async bhived client sharing one config (see :class:`bhived.BhivedClients`)."""

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("user_agent", USER_AGENT)
        super().__init__(**kwargs)
