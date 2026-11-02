"""Microsoft Agent Framework integration for bhived.

- :class:`BhivedContextProvider` recalls shared lessons before each run.
- :func:`bhived_tools` gives the agent ``bhived_query`` and the three explicit
  write tools.
"""

from ._clients import BhivedClients
from ._version import __version__
from .provider import BhivedContextProvider
from .tools import bhived_tools

__all__ = ["BhivedClients", "BhivedContextProvider", "__version__", "bhived_tools"]
