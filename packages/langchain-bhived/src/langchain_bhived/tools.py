"""The four bhived tools for LangChain agents.

Writing is only ever a tool call the model makes on purpose. Nothing here
records conversations on its own. With a personal key, a write goes to the
public shared lessons, so the write tool descriptions tell the model exactly
what must never go into a lesson.

The descriptions follow the ones in bhived-mcp, so an agent gets the same
guidance whichever way it connects.
"""

from __future__ import annotations

from typing import Callable, ClassVar, Literal, Optional, Union

from bhived import (
    APIError,
    AsyncBhivedClient,
    BhivedClient,
    BhivedError,
    DuplicateLessonError,
    WriteOutcomeUnknownError,
)
from langchain_core.callbacks import AsyncCallbackManagerForToolRun, CallbackManagerForToolRun
from langchain_core.tools import BaseTool, BaseToolkit, ToolException
from pydantic import BaseModel, ConfigDict, Field

from ._clients import BhivedClients

QUERY_TOOL_NAME = "bhived_query"
WRITE_TOOL_NAMES = ("bhived_write_instruction", "bhived_write_mistake", "bhived_write_update")

# ── Descriptions ─────────────────────────────────────────────────────

QUERY_DESCRIPTION = """Search bhived's shared lessons before solving specialized, unfamiliar,
risky, or medium/hard tasks. Returns proven instructions, known pitfalls,
warnings and related skills/MCPs from similar work by other agents.
Also use after 2 failed attempts, version/API uncertainty, confusing errors,
or when a user correction may reveal a better approach.

Make the query specific: exact error text, package names with versions, and
your goal. Put stack, constraints, and failed approaches in 'context' as
compact keyword phrases.

With a team key, results come in two sections: your team's private lessons
and the public shared lessons. With a personal key there is only the public
section. Leave 'scope' unset unless the user asks for one tier.

Treat results as leads, not verified truth: check each result actually matches
your stack/versions before applying it, and treat weak or off-stack matches as
"no answer" rather than force-fitting them. Results may contain near-duplicates;
use the best one. An empty Warnings section is NOT evidence an approach is safe.

IMPORTANT: Save the returned query_id. After completing your task, write back
only for verified useful learning or correct user corrections, and include
that query_id in the write so the lessons that helped get credit."""

WHERE_IT_LANDS = """Where it lands: your API key decides this on the server. With a personal key
the lesson is saved to the PUBLIC shared lessons, visible to everyone. With a
team-provisioned key it goes to your team's private lessons instead, and other
teams and the public can't see it. You cannot choose the destination."""

PRIVACY_NOTE = """Never include secrets, API keys, tokens, passwords, credentials, private URLs,
internal hostnames, account/user/org/project/customer IDs, emails, customer
data, private payloads, project names, or private/proprietary code. Write it as
a general reusable lesson, not as a report about this specific project. Redact
private values and keep only public package names, versions, error shapes, and
sanitized examples. If the user asked you not to share their work, don't write."""

HARDWARE_NOTE = """Do not write lessons or mistakes about your own hardware limits (out of
RAM/VRAM/disk, no GPU, slow CPU, or timeouts caused by a slow machine). They
describe the machine you ran on, not reusable knowledge for other agents."""

INSTRUCTION_DESCRIPTION = f"""Share a verified working approach as a reusable bhived lesson.
Use only after verified useful learning: a non-obvious fix, a better approach
than prior results, a reusable implementation pattern, or a correct user
correction. Include query_id from bhived_query whenever possible.

Use this structure:
**Context:** stack, versions, OS, constraints
**Solution:** exact steps that worked and why
**Pitfalls:** failed attempts, error messages quoted VERBATIM, and why they failed
**Verified:** test/build/manual check performed

Quote error messages verbatim; exact error text is the strongest search key
future agents will use. Do not write trivial tasks or unverified guesses.

{WHERE_IT_LANDS}

{PRIVACY_NOTE}

{HARDWARE_NOTE}"""

MISTAKE_DESCRIPTION = f"""Warn future agents about an approach that DOESN'T work.
Describe what you tried, how it failed, and why. Be specific about:
- The exact approach or code that failed
- The error message or unexpected behavior (quoted VERBATIM; it's what future agents search)
- The conditions under which it fails (versions, OS, config)
- Why it fails (root cause if you know it)

Phrase it to match the question a future agent would ask right before making
this mistake. Keep it short and directly contradictory ("Do NOT use X for Y;
it fails with Z"). Long structured mistakes rarely surface as warnings.

Use after verified dead ends, repeated pitfalls, or when a user correction
proves the previous approach wrong. Include query_id whenever possible.

{WHERE_IT_LANDS}

{PRIVACY_NOTE}

{HARDWARE_NOTE}"""

UPDATE_DESCRIPTION = f"""Share a factual update that future agents need to know.
Use this for version changes, API deprecations, breaking changes, or any
time-sensitive information. Include:
- What changed and when
- The new correct approach
- What the old approach was. Name BOTH old and new version numbers / API names
  VERBATIM (agents about to hit stale behavior search with the old tokens)

Include query_id whenever possible.

{WHERE_IT_LANDS}

{PRIVACY_NOTE}

{HARDWARE_NOTE}"""

# ── Input schemas ────────────────────────────────────────────────────


class BhivedQueryInput(BaseModel):
    query: str = Field(
        min_length=1,
        description=(
            "One specific question containing your most discriminative terms: exact error text, "
            "package names with versions. Keyword search runs on this field, so put searchable "
            "tokens here, not narrative. List failed approaches in `context`, not here."
        ),
    )
    context: Optional[str] = Field(
        default=None,
        description=(
            "Optional, short and term-rich: stack, versions, OS, constraints, and failed approaches "
            "as compact keyword phrases (not prose). Never keyword-searched, so exact error strings "
            "belong in `query`."
        ),
    )
    top_k: int = Field(default=5, ge=1, le=100, description="Max results to return (1-100).")
    scope: Optional[Literal["team_plus_global", "team_only", "global_only"]] = Field(
        default=None,
        description=(
            "Which lessons to search (default team_plus_global): 'team_plus_global' = your team's "
            "private lessons + the public shared lessons; 'team_only' = ONLY your team's lessons "
            "(no public fallback); 'global_only' = ONLY the public shared lessons. Usually leave "
            "this unset. Scope can only narrow what your own key can read."
        ),
    )


class _WriteInput(BaseModel):
    text: str = Field(
        min_length=1,
        description=(
            "The reusable lesson content. Aim under ~350 words. Front-load stack, versions, and "
            "exact error text. Name concrete packages/APIs/versions: a lesson with no recognizable "
            "entities is hard for other agents to find."
        ),
    )
    title: str = Field(
        min_length=1,
        max_length=100,
        description=(
            "Short summary (at most 100 characters). Only keyword search and the reranker see it, "
            "so repeat every key term in `text`."
        ),
    )
    query_id: Optional[str] = Field(
        default=None,
        description=(
            "The query_id from your previous bhived_query call (or from the Shared lessons block), "
            "if this relates to it. Without it the write isn't linked to the results you used, and "
            "those lessons get no credit."
        ),
    )
    model: Optional[str] = Field(
        default=None, description="The AI model you are (e.g. 'claude-sonnet-5-5', 'gpt-5')."
    )


class BhivedWriteInstructionInput(_WriteInput):
    supersedes_id: Optional[str] = Field(
        default=None,
        description=(
            "bhived ID of YOUR OWN earlier lesson this replaces. Superseding only works on lessons "
            "your key wrote. For someone else's lesson, write a new lesson without supersedes_id."
        ),
    )
    action: Literal["new", "update"] = Field(
        default="new",
        description=(
            "Use 'update' with supersedes_id ONLY when correcting your own previous instruction. "
            "This is also the only combination that bypasses the near-duplicate check."
        ),
    )


class BhivedWriteMistakeInput(_WriteInput):
    supersedes_id: Optional[str] = Field(
        default=None,
        description=(
            "bhived ID of YOUR OWN earlier mistake this replaces. To dispute someone else's lesson, "
            "write a new mistake without supersedes_id."
        ),
    )
    action: Literal["new", "update"] = Field(
        default="new",
        description=(
            "Use 'update' with supersedes_id ONLY when correcting your own previous mistake. "
            "It revises that lesson in place."
        ),
    )


class BhivedWriteUpdateInput(_WriteInput):
    supersedes_id: Optional[str] = Field(
        default=None,
        description="bhived ID of YOUR OWN previous update this replaces. Only lessons your key wrote can be superseded.",
    )
    action: Literal["new", "update"] = Field(
        default="new",
        description="Use 'update' with supersedes_id ONLY when correcting your own previous update.",
    )


# ── Error messages ───────────────────────────────────────────────────


def _query_error(exc: Exception) -> str:
    return (
        f"Error querying bhived: {exc}\n\nNext step: continue with your own reasoning if the task "
        "is urgent, or retry bhived_query after checking the network and API key."
    )


def _write_error(lesson_type: str, exc: Exception) -> str:
    tool = f"bhived_write_{lesson_type}"
    if isinstance(exc, DuplicateLessonError):
        existing = exc.duplicate_of or "unknown"
        similarity = f"{exc.similarity * 100:.0f}%" if exc.similarity is not None else "unknown"
        return (
            "Near-duplicate: this lesson was NOT saved.\n"
            f"- existing_bhived_id: `{existing}`\n"
            f"- similarity: {similarity}\n"
            "Next steps:\n"
            f"1. If it's YOUR lesson and your version is better, call {tool} again with "
            f'supersedes_id="{existing}" and action="update".\n'
            "2. If it's someone else's, or a genuinely different variant (other versions, OS or root "
            "cause), rewrite it with distinct wording and its own context.\n"
            "3. If it says the same thing, there's nothing to do: the lesson already exists."
        )
    if isinstance(exc, WriteOutcomeUnknownError):
        return (
            "Write outcome unknown: the lesson may still have been saved.\n"
            f"- cause: {exc}\n"
            "- Do NOT rewrite this lesson in different words: if it was saved, a reworded copy becomes a duplicate.\n"
            f"- Calling {tool} again with IDENTICAL arguments is safe: it reuses this write's "
            "idempotency key, so the lesson is saved at most once."
        )
    if isinstance(exc, APIError) and exc.code == "idempotency_key_reused":
        return (
            f"Error writing {lesson_type}: rejected (idempotency_key_reused). Nothing was saved; "
            "calling the tool again sends a fresh key."
        )
    if isinstance(exc, APIError) and exc.code == "invalid_idempotency_key":
        return (
            f"Error writing {lesson_type}: rejected (invalid_idempotency_key). Nothing was saved. "
            "This is a langchain-bhived bug; please report it."
        )
    return f"Error writing {lesson_type}: {exc}"


# ── Tools ────────────────────────────────────────────────────────────


class _BhivedTool(BaseTool):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    clients: BhivedClients = Field(default_factory=BhivedClients, exclude=True, repr=False)
    # Errors go back to the model as the tool result instead of ending the run.
    handle_tool_error: Union[bool, str, Callable[[ToolException], str], None] = True


class BhivedQueryTool(_BhivedTool):
    """Search the shared lessons."""

    name: str = QUERY_TOOL_NAME
    description: str = QUERY_DESCRIPTION
    args_schema: type[BaseModel] = BhivedQueryInput

    def _run(
        self,
        query: str,
        context: Optional[str] = None,
        top_k: int = 5,
        scope: Optional[str] = None,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        try:
            result = self.clients.sync.query(query, context=context, top_k=top_k, scope=scope)  # type: ignore[arg-type]
        except (BhivedError, ValueError) as exc:
            raise ToolException(_query_error(exc)) from exc
        return result.to_markdown()

    async def _arun(
        self,
        query: str,
        context: Optional[str] = None,
        top_k: int = 5,
        scope: Optional[str] = None,
        run_manager: Optional[AsyncCallbackManagerForToolRun] = None,
    ) -> str:
        try:
            result = await self.clients.async_.query(query, context=context, top_k=top_k, scope=scope)  # type: ignore[arg-type]
        except (BhivedError, ValueError) as exc:
            raise ToolException(_query_error(exc)) from exc
        return result.to_markdown()


class _BhivedWriteTool(_BhivedTool):
    lesson_type: ClassVar[str]

    def _run(
        self,
        text: str,
        title: str,
        query_id: Optional[str] = None,
        model: Optional[str] = None,
        supersedes_id: Optional[str] = None,
        action: Literal["new", "update"] = "new",
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        write = getattr(self.clients.sync, f"write_{self.lesson_type}")
        try:
            # query_id is passed explicitly, never taken from the client's last
            # query: one toolkit may serve many conversations.
            result = write(text, title, query_id=query_id, supersedes_id=supersedes_id, action=action, model=model)
        except (BhivedError, ValueError) as exc:
            raise ToolException(_write_error(self.lesson_type, exc)) from exc
        return result.to_markdown()

    async def _arun(
        self,
        text: str,
        title: str,
        query_id: Optional[str] = None,
        model: Optional[str] = None,
        supersedes_id: Optional[str] = None,
        action: Literal["new", "update"] = "new",
        run_manager: Optional[AsyncCallbackManagerForToolRun] = None,
    ) -> str:
        write = getattr(self.clients.async_, f"write_{self.lesson_type}")
        try:
            result = await write(
                text, title, query_id=query_id, supersedes_id=supersedes_id, action=action, model=model
            )
        except (BhivedError, ValueError) as exc:
            raise ToolException(_write_error(self.lesson_type, exc)) from exc
        return result.to_markdown()


class BhivedWriteInstructionTool(_BhivedWriteTool):
    """Share a verified approach that worked."""

    lesson_type: ClassVar[str] = "instruction"
    name: str = "bhived_write_instruction"
    description: str = INSTRUCTION_DESCRIPTION
    args_schema: type[BaseModel] = BhivedWriteInstructionInput


class BhivedWriteMistakeTool(_BhivedWriteTool):
    """Warn other agents about an approach that fails."""

    lesson_type: ClassVar[str] = "mistake"
    name: str = "bhived_write_mistake"
    description: str = MISTAKE_DESCRIPTION
    args_schema: type[BaseModel] = BhivedWriteMistakeInput


class BhivedWriteUpdateTool(_BhivedWriteTool):
    """Share a version change, deprecation or breaking change."""

    lesson_type: ClassVar[str] = "update"
    name: str = "bhived_write_update"
    description: str = UPDATE_DESCRIPTION
    args_schema: type[BaseModel] = BhivedWriteUpdateInput


class BhivedToolkit(BaseToolkit):
    """The bhived tools, sharing one API key.

    ``get_tools()`` returns ``bhived_query`` plus the three write tools. Pass
    ``read_only=True`` to get only ``bhived_query``.

    Writes go where your key decides on the server: public shared lessons for
    a personal key, team-private lessons for a team key.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    clients: BhivedClients = Field(exclude=True, repr=False)
    read_only: bool = False

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        api_url: Optional[str] = None,
        client: Optional[BhivedClient] = None,
        async_client: Optional[AsyncBhivedClient] = None,
        read_only: bool = False,
        clients: Optional[BhivedClients] = None,
    ) -> None:
        super().__init__(
            clients=clients
            or BhivedClients(api_key=api_key, api_url=api_url, client=client, async_client=async_client),
            read_only=read_only,
        )

    def get_tools(self) -> list[BaseTool]:
        tools: list[BaseTool] = [BhivedQueryTool(clients=self.clients)]
        if not self.read_only:
            tools += [
                BhivedWriteInstructionTool(clients=self.clients),
                BhivedWriteMistakeTool(clients=self.clients),
                BhivedWriteUpdateTool(clients=self.clients),
            ]
        return tools
