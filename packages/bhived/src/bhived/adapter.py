"""Shared pieces for framework adapters (LangChain, Strands, Microsoft Agent Framework).

Every adapter gives the model the same four tools and the same guidance, so the
text lives here once: tool descriptions, parameter descriptions and error
messages. They follow the wording in bhived-mcp, so an agent gets the same
advice whichever way it connects.

The other helpers are the parts of "recall before the model runs" that don't
depend on a framework: a small query cache and a logger that warns once per
kind of failure.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from typing import Optional

from ._errors import APIError, BhivedError, DuplicateLessonError, WriteOutcomeUnknownError
from ._types import QueryResult

QUERY_TOOL_NAME = "bhived_query"
WRITE_TOOL_NAMES = ("bhived_write_instruction", "bhived_write_mistake", "bhived_write_update")

# ── Tool descriptions ────────────────────────────────────────────────

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

WRITE_DESCRIPTIONS = {
    "instruction": INSTRUCTION_DESCRIPTION,
    "mistake": MISTAKE_DESCRIPTION,
    "update": UPDATE_DESCRIPTION,
}

# ── Parameter descriptions ───────────────────────────────────────────

QUERY_PARAMS = {
    "query": (
        "One specific question containing your most discriminative terms: exact error text, "
        "package names with versions. Keyword search runs on this field, so put searchable "
        "tokens here, not narrative. List failed approaches in `context`, not here."
    ),
    "context": (
        "Optional, short and term-rich: stack, versions, OS, constraints, and failed approaches "
        "as compact keyword phrases (not prose). Never keyword-searched, so exact error strings "
        "belong in `query`."
    ),
    "top_k": "Max results to return (1-100).",
    "scope": (
        "Which lessons to search (default team_plus_global): 'team_plus_global' = your team's "
        "private lessons + the public shared lessons; 'team_only' = ONLY your team's lessons "
        "(no public fallback); 'global_only' = ONLY the public shared lessons. Usually leave "
        "this unset. Scope can only narrow what your own key can read."
    ),
}

WRITE_PARAMS = {
    "text": (
        "The reusable lesson content. Aim under ~350 words. Front-load stack, versions, and "
        "exact error text. Name concrete packages/APIs/versions: a lesson with no recognizable "
        "entities is hard for other agents to find."
    ),
    "title": (
        "Short summary (at most 100 characters). Only keyword search and the reranker see it, "
        "so repeat every key term in `text`."
    ),
    "query_id": (
        "The query_id from your previous bhived_query call (or from the Shared lessons block), "
        "if this relates to it. Without it the write isn't linked to the results you used, and "
        "those lessons get no credit."
    ),
    "model": "The AI model you are (e.g. 'claude-sonnet-5-5', 'gpt-5').",
}

SUPERSEDES_PARAMS = {
    "instruction": (
        "bhived ID of YOUR OWN earlier lesson this replaces. Superseding only works on lessons "
        "your key wrote. For someone else's lesson, write a new lesson without supersedes_id."
    ),
    "mistake": (
        "bhived ID of YOUR OWN earlier mistake this replaces. To dispute someone else's lesson, "
        "write a new mistake without supersedes_id."
    ),
    "update": "bhived ID of YOUR OWN previous update this replaces. Only lessons your key wrote can be superseded.",
}

ACTION_PARAMS = {
    "instruction": (
        "Use 'update' with supersedes_id ONLY when correcting your own previous instruction. "
        "This is also the only combination that bypasses the near-duplicate check."
    ),
    "mistake": (
        "Use 'update' with supersedes_id ONLY when correcting your own previous mistake. "
        "It revises that lesson in place."
    ),
    "update": "Use 'update' with supersedes_id ONLY when correcting your own previous update.",
}

# ── Error messages (returned to the model as the tool result) ────────


def query_error_message(exc: Exception) -> str:
    return (
        f"Error querying bhived: {exc}\n\nNext step: continue with your own reasoning if the task "
        "is urgent, or retry bhived_query after checking the network and API key."
    )


def write_error_message(lesson_type: str, exc: Exception) -> str:
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
            "This is a bug in the bhived package; please report it."
        )
    return f"Error writing {lesson_type}: {exc}"


# ── Recall helpers ───────────────────────────────────────────────────


def clean_query(text: Optional[str], *, min_chars: int, max_chars: int) -> Optional[str]:
    """Trim a user message into query text. None when it's too short to be worth a search."""
    if not text:
        return None
    text = text.strip()
    if len(text) < min_chars:
        return None
    return text[:max_chars]


class RecallCache:
    """Recent query results, keyed by query text.

    An agent calls the model several times per user turn (once after each
    tool call). The cache turns that into one bhived query. Thread-safe.
    """

    def __init__(self, size: int = 128, ttl: float = 600.0) -> None:
        self.size = size
        self.ttl = ttl
        self._items: OrderedDict[str, tuple[float, QueryResult]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, query: str) -> Optional[QueryResult]:
        if self.size <= 0:
            return None
        with self._lock:
            entry = self._items.get(query)
            if entry is None:
                return None
            stored_at, result = entry
            if time.monotonic() - stored_at > self.ttl:
                del self._items[query]
                return None
            self._items.move_to_end(query)
            return result

    def put(self, query: str, result: QueryResult) -> None:
        if self.size <= 0:
            return
        with self._lock:
            self._items[query] = (time.monotonic(), result)
            self._items.move_to_end(query)
            while len(self._items) > self.size:
                self._items.popitem(last=False)


class FailureLog:
    """Logs a failed recall at WARNING the first time each kind of error happens, then at DEBUG.

    Without this, a missing key would log on every model call.
    """

    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger
        self._seen: set[str] = set()

    def report(self, exc: BhivedError) -> None:
        kind = type(exc).__name__
        level = logging.DEBUG if kind in self._seen else logging.WARNING
        self._seen.add(kind)
        self.logger.log(level, "bhived recall skipped (%s): %s", kind, exc)
