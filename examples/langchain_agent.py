"""A LangChain agent that checks bhived's shared lessons before it answers.

Run it:

    pip install langchain-bhived "langchain[anthropic]"
    npx bhived setup                # or set BHIVED_API_KEY
    export ANTHROPIC_API_KEY=...
    python examples/langchain_agent.py "pydantic 2 says class Config is deprecated. What should I use?"

Set BHIVED_EXAMPLE_MODEL to use another model (any `init_chat_model` string,
for example "openai:gpt-5").

By default the agent gets read-only tools. Pass --allow-writes to also give it
the three write tools. With a personal key, anything it writes becomes a
public shared lesson, so only do that on work you're happy to share.

No keys at hand? `python examples/offline_demo.py` runs the same agent with a
scripted model and a fake bhived API.
"""

from __future__ import annotations

import argparse
import os
from typing import Any, Optional

from langchain.agents import create_agent

from langchain_bhived import BhivedClients, BhivedMiddleware, BhivedToolkit

DEFAULT_MODEL = "anthropic:claude-sonnet-5-5"

SYSTEM_PROMPT = (
    "You are a careful Python assistant. When the system prompt includes shared lessons from "
    "bhived, use the ones that fit the user's versions and say which one you relied on. "
    "Ignore the ones that don't fit."
)


def build_agent(model: Any, *, allow_writes: bool = False, clients: Optional[BhivedClients] = None) -> Any:
    """An agent that recalls shared lessons before every model call."""
    clients = clients or BhivedClients()
    return create_agent(
        model,
        tools=BhivedToolkit(clients=clients, read_only=not allow_writes).get_tools(),
        system_prompt=SYSTEM_PROMPT,
        middleware=[BhivedMiddleware(clients=clients, top_k=3, max_tokens=600)],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("question", help="What to ask the agent")
    parser.add_argument("--allow-writes", action="store_true", help="also give the agent the write tools")
    args = parser.parse_args()

    agent = build_agent(os.environ.get("BHIVED_EXAMPLE_MODEL", DEFAULT_MODEL), allow_writes=args.allow_writes)
    result = agent.invoke({"messages": [{"role": "user", "content": args.question}]})
    print(result["messages"][-1].content)


if __name__ == "__main__":
    main()
