"""LangChain integration for bhived.

- :class:`BhivedMiddleware` recalls shared lessons before each model call.
- :class:`BhivedToolkit` gives the agent ``bhived_query`` and the three
  explicit write tools.
"""

from ._clients import BhivedClients
from ._version import __version__
from .middleware import BhivedMiddleware
from .tools import (
    QUERY_TOOL_NAME,
    WRITE_TOOL_NAMES,
    BhivedQueryTool,
    BhivedToolkit,
    BhivedWriteInstructionTool,
    BhivedWriteMistakeTool,
    BhivedWriteUpdateTool,
)

__all__ = [
    "QUERY_TOOL_NAME",
    "WRITE_TOOL_NAMES",
    "BhivedClients",
    "BhivedMiddleware",
    "BhivedQueryTool",
    "BhivedToolkit",
    "BhivedWriteInstructionTool",
    "BhivedWriteMistakeTool",
    "BhivedWriteUpdateTool",
    "__version__",
]
