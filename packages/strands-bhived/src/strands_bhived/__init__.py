"""Strands Agents integration for bhived.

- :class:`BhivedPlugin` recalls shared lessons before the model answers.
- :func:`bhived_tools` gives the agent ``bhived_query`` and the three
  explicit write tools.
"""

from ._clients import BhivedClients
from ._version import __version__
from .plugin import BhivedPlugin
from .tools import bhived_tools

__all__ = ["BhivedClients", "BhivedPlugin", "__version__", "bhived_tools"]
